#!/usr/bin/env python3
"""Build infra/matrix-all.yaml, the one-template, one-form deployment, from the separate templates in infra/.

    python tools/build-all-template.py

Plain text assembly, no third-party packages. Re-run it whenever matrix-table, matrix-core, matrix-iam-executor,
matrix-playbook or matrix-app change, then lint the result:  cfn-lint infra/matrix-all.yaml
"""
import pathlib
import re
import sys

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"
OUT = INFRA / "matrix-all.yaml"

HEAD = re.compile(r"^  ([A-Za-z0-9]+):\s*$")


def read(name):
    return (INFRA / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def section(text, key):
    """Body of a top-level YAML section (the lines under `key:` up to the next top-level key)."""
    out, on = [], False
    for ln in text.split("\n"):
        if re.match(r"^[A-Za-z]", ln):
            if on:
                break
            if ln.startswith(key + ":"):
                on = True
            continue
        if on:
            out.append(ln)
    return "\n".join(out).strip("\n")


def blocks(body):
    """Split a section body into an ordered {name: text}. Comments and blank lines above a key travel with it."""
    res, pending, cur = {}, [], None
    for ln in body.split("\n"):
        m = HEAD.match(ln)
        if m:
            cur = m.group(1)
            res[cur] = pending + [ln]
            pending = []
        elif ln.strip() == "" or re.match(r"^  #", ln):
            pending.append(ln)
        elif cur is not None:
            res[cur] += pending + [ln]
            pending = []
    return {k: "\n".join(v).rstrip("\n") for k, v in res.items()}


def pick(src, keep=None, drop=()):
    return {k: v for k, v in src.items() if k not in drop and (keep is None or k in keep)}


def merge(*parts):
    out = {}
    for p in parts:
        for k, v in p.items():
            if k in out:
                sys.exit("duplicate logical name in merge: " + k)
            out[k] = v
    return out


def swap(text, old, new, count=1):
    if text.count(old) != count:
        sys.exit("expected %d x %r, found %d" % (count, old, text.count(old)))
    return text.replace(old, new)


table, core, exe, play, app = (read(n) for n in ("matrix-table.yaml", "matrix-core.yaml", "matrix-iam-executor.yaml",
                                                  "matrix-playbook.yaml", "matrix-app.yaml"))

# ---------------------------------------------------------------- parameters
app_params_dropped = {"FunctionName", "LambdaRoleArn", "Environment", "ExecutorRoleArn", "DecommissionRoleArn", "InstanceProfile",
                      "AuditLogGroup", "OpsBucket", "TraceTable", "OperatorRoleArn"}
params = merge(
    pick(blocks(section(core, "Parameters")), keep=("FunctionName", "ReadAccess", "OperatorRoleArn")),
    pick(blocks(section(exe, "Parameters")), keep=("Environment", "EnableDecommissionRole")),
    pick(blocks(section(app, "Parameters")), drop=app_params_dropped),
)
params["CodeBucket"] = ("  CodeBucket:\n    Type: String\n"
                        "    Description: Name of an S3 bucket you created by hand, with matrix-lambda.zip already uploaded to it")
params["WebsiteUrl"] = ("  WebsiteUrl:\n    Type: String\n    Default: '*'\n"
                        "    Description: Origin allowed to call the Function URL. Keep * when you open matrix-ui.html from your PC. "
                        "Use your website address if you host the page in S3.")
order = ["CodeBucket", "CodeKey", "FunctionName", "Environment", "WebsiteUrl"] + [k for k in params if k not in
                                                                                  ("CodeBucket", "CodeKey", "FunctionName", "Environment", "WebsiteUrl")]
params = {k: params[k] for k in order}

# ---------------------------------------------------------------- conditions
conditions = section(core, "Conditions") + "\n" + section(exe, "Conditions")

# ---------------------------------------------------------------- resources
res = merge(
    pick(blocks(section(table, "Resources")), drop=("LambdaTablesPolicy",)),
    pick(blocks(section(core, "Resources")), drop=("ArtifactBucket",)),
    blocks(section(exe, "Resources")),
    blocks(section(play, "Resources")),
    blocks(section(app, "Resources")),
)
text = "\n\n".join(res.values())
# the executor roles now trust the Lambda role created in this same template
text = swap(text, "Principal: { AWS: !Ref TrustedLambdaRoleArn }", "Principal: { AWS: !GetAtt LambdaRole.Arn }", count=2)
# the function takes its role and the executor settings straight from the resources above
text = swap(text, "Role: !Ref LambdaRoleArn", "Role: !GetAtt LambdaRole.Arn")
text = swap(text, "EXECUTOR_ROLE_ARN: !Ref ExecutorRoleArn", "EXECUTOR_ROLE_ARN: !GetAtt ExecutorRole.Arn")
text = swap(text, "DECOMMISSION_ROLE_ARN: !Ref DecommissionRoleArn",
            "DECOMMISSION_ROLE_ARN: !If [DecomEnabled, !GetAtt DecommissionRole.Arn, '']")
text = swap(text, "    Type: AWS::Lambda::Function\n    Properties:", "    Type: AWS::Lambda::Function\n    DependsOn: LogGroup\n    Properties:")

# ---------------------------------------------------------------- outputs
outs = merge(
    pick(blocks(section(core, "Outputs")), drop=("ArtifactBucketName",)),
    blocks(section(exe, "Outputs")),
    blocks(section(app, "Outputs")),
)

metadata = """Metadata:
  AWS::CloudFormation::Interface:
    ParameterGroups:
      - Label: { default: Code (create this bucket and upload the zip first) }
        Parameters: [CodeBucket, CodeKey, FunctionName, Environment, WebsiteUrl]
      - Label: { default: ServiceNow }
        Parameters: [SnBase, SnUser, SnPass, SnAiUser, SnAiGroup, SnL2Group, SnL3Group, L1Group, L2Group]
      - Label: { default: Sign-in }
        Parameters: [TokenSecret, UsersJson, LeadRoles, AgentKey]
      - Label: { default: LLM primary }
        Parameters: [LlmUrl, LlmApiKey, LlmModel, LlmSmallModel, LlmExtraModels]
      - Label: { default: LLM standby 1 }
        Parameters: [Fb1Url, Fb1Key, Fb1Model]
      - Label: { default: LLM standby 2 }
        Parameters: [Fb2Url, Fb2Key, Fb2Model]
      - Label: { default: LLM standby 3 }
        Parameters: [Fb3Url, Fb3Key, Fb3Model]
      - Label: { default: AWS operations }
        Parameters: [ReadAccess, OperatorRoleArn, EnableDecommissionRole, SubnetId, SecurityGroupId, MaxVcpu, AllowedTypes, Services, IngestUrl, TfProject, TfModules, Playbooks]
      - Label: { default: Agent behaviour }
        Parameters: [KbName, LlmPrices, AutoAfter, Families, RagMin, RagRequired, LearnScan, EvalHost]"""

doc = """AWSTemplateFormatVersion: '2010-09-09'
Description: MATRIX complete stack - tables, buckets, Lambda role, scoped executor role, SSM playbooks, the console Lambda, its Function URL and the learning schedule. One template, one form.
# GENERATED by tools/build-all-template.py from the separate templates in this folder. Edit those, then re-run the script.

%s

Parameters:
%s

Conditions:
%s

Resources:
%s

Outputs:
%s
""" % (metadata, "\n".join(params.values()), conditions.strip("\n"), text, "\n".join(outs.values()))

# every parameter named in the Metadata groups must exist, and the other way round
grouped = set(re.findall(r"[A-Za-z0-9]+", " ".join(re.findall(r"Parameters: \[(.*?)\]", metadata))))
if grouped != set(params):
    sys.exit("metadata groups and parameters differ: only in groups %s; only in parameters %s" % (sorted(grouped - set(params)), sorted(set(params) - grouped)))

OUT.write_text(doc, encoding="utf-8", newline="\n")
print("wrote %s: %d parameters, %d resources, %d outputs, %d bytes" % (OUT, len(params), len(res), len(outs), len(doc.encode())))
