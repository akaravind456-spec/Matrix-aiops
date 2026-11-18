"""
matrix_ops_skills.py - AWS operations used by matrix_ops_install.py: patching, migration, deployment, decommission.

Rules every function follows
  * Every change runs with the scoped executor role (matrix_guardrails._session), never the Lambda's own role.
  * Every change needs approved=True (set only by the engineer pressing Confirm) and a real CHG number that
    ServiceNow says is approved and scheduled. The agent cannot approve its own change.
  * Only instances tagged matrix-managed=true and environment=<ENVIRONMENT> are touched.
  * Every function returns a plain dict {"ok": True, ...} or {"ok": False, "error": "..."} and never raises.
  * A work note goes on the ticket and an entry goes to the audit log for every change.
  * Decommission: stop and snapshot are done here. Terminate is a separate, opt-in step (see decommission_terminate).
"""
import json
import os
import re
import time

import boto3

import matrix_guardrails as gr
import matrix_mode as mode

HOLD_DAYS = int(os.environ.get("DECOM_HOLD_DAYS", "7"))
DECOM_ROLE = os.environ.get("DECOMMISSION_ROLE_ARN", "").strip()
PATCH_DOC = "AWS-RunPatchBaseline"
SCAN_DOC = "MATRIX_PATCH_SCAN"


# ----------------------------------------------------------------- helpers
def _fail(msg):
    return {"ok": False, "error": str(msg)[:400]}


def _safe(fn):
    def wrap(**kw):
        try:
            return fn(**kw)
        except Exception as e:  # never crash the agent loop
            return _fail("%s: %s" % (type(e).__name__, e))
    wrap.__name__ = fn.__name__
    wrap.__doc__ = fn.__doc__
    return wrap


def _sess(region=None):
    s = gr._session()
    if region and region != gr.REGION:
        c = s.get_credentials().get_frozen_credentials()
        return boto3.Session(aws_access_key_id=c.access_key, aws_secret_access_key=c.secret_key,
                             aws_session_token=c.token, region_name=region)
    return s


def _change(change_number, approved):
    """Gate for every change. Returns (error_dict, None) or (None, servicenow_record)."""
    if not approved:
        return _fail("needs_approval: the engineer must press Confirm first"), None
    num = str(change_number or "").strip().upper()
    if not re.fullmatch(mode.number_regex(), num):
        return _fail("an incident number (INC...) is required for this action" if mode.incident_mode() else "a change number (CHG...) is required for this action"), None
    os.environ["CURRENT_TICKET"] = num
    ok, why, rec = gr.validate_ticket(num)
    if not ok:
        return _fail("ticket_invalid: " + why), None
    return None, rec


def _rec(ticket):
    """Optional ticket for read-only tools: returns the record (for work notes) or None."""
    t = str(ticket or "").strip().upper()
    if not re.fullmatch(r"(CHG|INC)\d{7,}", t):
        return None
    try:
        return gr.validate_ticket(t)[2]
    except Exception:
        return None


def _note(rec, text):
    gr.worknote(rec, text)


def _audit(action, ticket, **kw):
    gr._audit(dict(action=action, ticket=ticket, **kw))


def _targets(sess, ids):
    """All instances must be matrix-managed in this environment. Returns error dict or None."""
    if not ids:
        return _fail("no servers given")
    for i in ids:
        ok, why = gr._instance_ok(sess, i)
        if not ok:
            return _fail("%s: %s" % (i, why))
    return None


def _inst(sess, iid):
    r = sess.client("ec2").describe_instances(InstanceIds=[iid])["Reservations"]
    if not r:
        raise RuntimeError("instance %s not found" % iid)
    return r[0]["Instances"][0]


def _name(inst):
    return next((t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"), inst["InstanceId"])


def _wait_state(ec2, iid, want, tries=18, delay=5):
    for _ in range(tries):
        st = ec2.describe_instances(InstanceIds=[iid])["Reservations"][0]["Instances"][0]["State"]["Name"]
        if st == want:
            return True
        time.sleep(delay)
    return False


def _tags(change, extra=None):
    t = [{"Key": "matrix-managed", "Value": "true"}, {"Key": "environment", "Value": gr.ENV},
         {"Key": "change", "Value": change}]
    return t + [{"Key": k, "Value": str(v)} for k, v in (extra or {}).items()]


def _mk_image(sess, iid, change, purpose):
    ec2 = sess.client("ec2")
    inst = _inst(sess, iid)
    nm = "matrix-%s-%s-%s" % (purpose, re.sub(r"[^A-Za-z0-9-]", "", _name(inst))[:40], time.strftime("%Y%m%d%H%M%S"))
    r = ec2.create_image(InstanceId=iid, Name=nm, NoReboot=True,
                         Description="MATRIX %s for %s" % (purpose, change),
                         TagSpecifications=[{"ResourceType": t, "Tags": _tags(change, {"matrix-source-instance": iid, "matrix-purpose": purpose})}
                                            for t in ("image", "snapshot")])
    return r["ImageId"]


# ----------------------------------------------------------------- patching
@_safe
def patch_scan(instance_ids=None, ticket=None):
    """Read-only list of available security updates (MATRIX_PATCH_SCAN)."""
    sess = _sess()
    err = _targets(sess, instance_ids)
    if err:
        return err
    sent = sess.client("ssm").send_command(InstanceIds=instance_ids, DocumentName=SCAN_DOC, TimeoutSeconds=120,
                                           Comment=("patch scan " + str(ticket or ""))[:100])
    cid = sent["Command"]["CommandId"]
    _note(_rec(ticket), "Patch scan started on %s (command %s)" % (", ".join(instance_ids), cid))
    return {"ok": True, "command_id": cid, "next": "call patch_status with this command_id in about 30 seconds"}


@_safe
def patch_status(command_id=None, instance_ids=None, ticket=None):
    """Progress of a scan or install, plus a post-patch health check when it finished."""
    sess = _sess()
    ssm, ec2 = sess.client("ssm"), sess.client("ec2")
    out, done = [], True
    for i in instance_ids or []:
        try:
            r = ssm.get_command_invocation(CommandId=command_id, InstanceId=i)
        except ssm.exceptions.InvocationDoesNotExist:
            out.append({"instance_id": i, "status": "Pending"})
            done = False
            continue
        row = {"instance_id": i, "status": r["Status"], "output": (r.get("StandardOutputContent") or "")[:1200]}
        if r["Status"] in ("Pending", "InProgress", "Delayed"):
            done = False
        elif r["Status"] == "Success":
            st = ec2.describe_instance_status(InstanceIds=[i], IncludeAllInstances=True)["InstanceStatuses"]
            row["checks"] = ("%s/%s" % (st[0]["InstanceStatus"]["Status"], st[0]["SystemStatus"]["Status"])) if st else "unknown"
        out.append(row)
    if done:
        _note(_rec(ticket), "Patch job %s finished: %s" % (command_id, "; ".join("%s %s" % (r["instance_id"], r["status"]) for r in out)))
    return {"ok": True, "finished": done, "servers": out}


@_safe
def patch_install(instance_ids=None, change_number=None, approved=False, reboot_option="RebootIfNeeded"):
    """Rollback AMIs first, then install patches. Needs an approved change and Confirm."""
    err, rec = _change(change_number, approved)
    if err:
        return err
    if reboot_option not in ("RebootIfNeeded", "NoReboot"):
        return _fail("reboot_option must be RebootIfNeeded or NoReboot")
    sess = _sess()
    err = _targets(sess, instance_ids)
    if err:
        return err
    images = {}
    for i in instance_ids:  # rollback point for every server before anything changes
        images[i] = _mk_image(sess, i, change_number, "prepatch")
    sent = sess.client("ssm").send_command(
        InstanceIds=instance_ids, DocumentName=PATCH_DOC, TimeoutSeconds=600,
        Parameters={"Operation": ["Install"], "RebootOption": [reboot_option]}, Comment=("patch " + change_number)[:100])
    cid = sent["Command"]["CommandId"]
    _note(rec, "Patching %s. Rollback AMIs: %s. Command %s, reboot=%s." % (", ".join(instance_ids), json.dumps(images), cid, reboot_option))
    _audit("patch_install", change_number, instances=instance_ids, images=images, command_id=cid)
    return {"ok": True, "command_id": cid, "rollback_images": images, "next": "check progress with patch_status"}


# ----------------------------------------------------------------- migration
@_safe
def migration_assess(instance_id=None, ticket=None):
    """Read-only inventory before migrating a server."""
    sess = _sess()
    err = _targets(sess, [instance_id])
    if err:
        return err
    i = _inst(sess, instance_id)
    ec2 = sess.client("ec2")
    vols = [{"id": b["Ebs"]["VolumeId"], "device": b["DeviceName"]} for b in i.get("BlockDeviceMappings", []) if "Ebs" in b]
    if vols:
        for v in ec2.describe_volumes(VolumeIds=[x["id"] for x in vols])["Volumes"]:
            for x in vols:
                if x["id"] == v["VolumeId"]:
                    x.update(size_gb=v["Size"], type=v["VolumeType"], encrypted=v["Encrypted"])
    eips = [a["AllocationId"] for a in ec2.describe_addresses(Filters=[{"Name": "instance-id", "Values": [instance_id]}])["Addresses"]]
    res = {"name": _name(i), "instance_id": instance_id, "type": i["InstanceType"], "az": i["Placement"]["AvailabilityZone"],
           "subnet_id": i.get("SubnetId"), "vpc_id": i.get("VpcId"), "private_ip": i.get("PrivateIpAddress"),
           "security_groups": [g["GroupId"] for g in i.get("SecurityGroups", [])], "volumes": vols, "elastic_ips": eips,
           "iam_profile": (i.get("IamInstanceProfile") or {}).get("Arn"), "state": i["State"]["Name"],
           "tags": {t["Key"]: t["Value"] for t in i.get("Tags", [])}}
    _note(_rec(ticket), "Migration assessment of %s: %s, %d volume(s), EIPs %s" % (res["name"], res["type"], len(vols), eips or "none"))
    return {"ok": True, "assessment": res}


@_safe
def migration_replicate(instance_id=None, change_number=None, approved=False, target_region=None):
    """Create an AMI of the source server (no reboot)."""
    err, rec = _change(change_number, approved)
    if err:
        return err
    sess = _sess()
    err = _targets(sess, [instance_id])
    if err:
        return err
    img = _mk_image(sess, instance_id, change_number, "migration")
    _note(rec, "Migration image %s created from %s (target region: %s)." % (img, instance_id, target_region or gr.REGION))
    _audit("migration_replicate", change_number, instance=instance_id, image=img)
    return {"ok": True, "image_id": img, "next": "call migration_image_status until it is available"}


@_safe
def migration_image_status(image_id=None, region=None):
    sess = _sess(region)
    imgs = sess.client("ec2").describe_images(ImageIds=[image_id])["Images"]
    if not imgs:
        return _fail("image %s not found in %s" % (image_id, region or gr.REGION))
    return {"ok": True, "image_id": image_id, "state": imgs[0]["State"], "region": region or gr.REGION}


@_safe
def migration_copy_image(image_id=None, target_region=None, change_number=None, approved=False):
    """Copy an image to another region. The executor role must be allowed in that region (see docs)."""
    err, rec = _change(change_number, approved)
    if err:
        return err
    sess = _sess(target_region)
    src = _sess().client("ec2").describe_images(ImageIds=[image_id])["Images"]
    if not src:
        return _fail("image %s not found" % image_id)
    r = sess.client("ec2").copy_image(SourceImageId=image_id, SourceRegion=gr.REGION, Name=src[0]["Name"][:120] + "-copy", Encrypted=True)
    _note(rec, "Copying %s to %s as %s" % (image_id, target_region, r["ImageId"]))
    _audit("migration_copy_image", change_number, image=image_id, new_image=r["ImageId"], region=target_region)
    return {"ok": True, "image_id": r["ImageId"], "region": target_region}


@_safe
def migration_launch(image_id=None, subnet_id=None, instance_type=None, security_group_ids=None, change_number=None,
                     approved=False, iam_profile_name=None, name_tag=None, region=None):
    """Launch the target server from the migration image, tagged so the agent can manage it afterwards."""
    err, rec = _change(change_number, approved)
    if err:
        return err
    if not (subnet_id and instance_type and security_group_ids):
        return _fail("subnet_id, instance_type and security_group_ids are required")
    sess = _sess(region)
    ec2 = sess.client("ec2")
    try:
        ec2.describe_instance_types(InstanceTypes=[instance_type])
    except Exception:
        return _fail("%s is not a valid instance type in this region" % instance_type)
    nm = name_tag or "migrated-" + time.strftime("%Y%m%d%H%M")
    prof = iam_profile_name or os.environ.get("INSTANCE_PROFILE")
    kw = dict(ImageId=image_id, InstanceType=instance_type, MinCount=1, MaxCount=1, SubnetId=subnet_id,
              SecurityGroupIds=security_group_ids, MetadataOptions={"HttpTokens": "required"},
              TagSpecifications=[{"ResourceType": t, "Tags": _tags(change_number, {"Name": nm})} for t in ("instance", "volume")])
    if prof:
        kw["IamInstanceProfile"] = {"Name": prof}
    r = ec2.run_instances(**kw)
    iid = r["Instances"][0]["InstanceId"]
    _note(rec, "Launched %s (%s, %s) from %s." % (nm, iid, instance_type, image_id))
    _audit("migration_launch", change_number, instance=iid, image=image_id)
    return {"ok": True, "instance_id": iid, "name": nm, "next": "call migration_validate once it is running"}


@_safe
def migration_validate(instance_id=None, ticket=None, region=None):
    """Status checks and SSM agent for a new or migrated server."""
    sess = _sess(region)
    ec2, ssm = sess.client("ec2"), sess.client("ssm")
    st = ec2.describe_instance_status(InstanceIds=[instance_id], IncludeAllInstances=True)["InstanceStatuses"]
    if not st:
        return _fail("%s not found" % instance_id)
    s = st[0]
    info = ssm.describe_instance_information(Filters=[{"Key": "InstanceIds", "Values": [instance_id]}])["InstanceInformationList"]
    res = {"instance_id": instance_id, "state": s["InstanceState"]["Name"], "instance_check": s["InstanceStatus"]["Status"],
           "system_check": s["SystemStatus"]["Status"], "ssm": info[0]["PingStatus"] if info else "not registered"}
    res["healthy"] = res["state"] == "running" and res["instance_check"] == "ok" and res["system_check"] == "ok" and res["ssm"] == "Online"
    _note(_rec(ticket), "Validation of %s: %s" % (instance_id, json.dumps(res)))
    return {"ok": True, "validation": res}


def _move_eip(ec2, alloc, instance_id):
    ec2.associate_address(AllocationId=alloc, InstanceId=instance_id, AllowReassociation=True)


@_safe
def migration_cutover(source_id=None, target_id=None, change_number=None, approved=False, eip_allocation_id=None):
    """Stop the source and move the Elastic IP to the target, only if the target is healthy."""
    err, rec = _change(change_number, approved)
    if err:
        return err
    sess = _sess()
    err = _targets(sess, [source_id, target_id])
    if err:
        return err
    v = migration_validate(instance_id=target_id)
    if not v.get("ok") or not v["validation"]["healthy"]:
        return _fail("target %s is not healthy yet: %s" % (target_id, json.dumps(v.get("validation") or v.get("error"))))
    ec2 = sess.client("ec2")
    ec2.stop_instances(InstanceIds=[source_id])
    if not _wait_state(ec2, source_id, "stopped"):
        return _fail("source %s did not stop in time. Nothing was moved; check it and retry." % source_id)
    if eip_allocation_id:
        _move_eip(ec2, eip_allocation_id, target_id)
    msg = "Cutover: %s stopped, %s is live%s." % (source_id, target_id, (", EIP moved" if eip_allocation_id else ". No EIP given: update DNS or the load balancer yourself"))
    _note(rec, msg)
    _audit("migration_cutover", change_number, source=source_id, target=target_id, eip=eip_allocation_id)
    return {"ok": True, "message": msg}


@_safe
def migration_rollback(source_id=None, target_id=None, change_number=None, approved=False, eip_allocation_id=None):
    """Start the source again, give it the Elastic IP back, stop the target."""
    err, rec = _change(change_number, approved)
    if err:
        return err
    sess = _sess()
    err = _targets(sess, [source_id, target_id])
    if err:
        return err
    ec2 = sess.client("ec2")
    ec2.start_instances(InstanceIds=[source_id])
    if not _wait_state(ec2, source_id, "running"):
        return _fail("source %s did not start in time; check it in the console" % source_id)
    if eip_allocation_id:
        _move_eip(ec2, eip_allocation_id, source_id)
    ec2.stop_instances(InstanceIds=[target_id])
    msg = "Rollback: %s running again, %s stopped." % (source_id, target_id)
    _note(rec, msg)
    _audit("migration_rollback", change_number, source=source_id, target=target_id)
    return {"ok": True, "message": msg}


# ----------------------------------------------------------------- deployment
@_safe
def deployment_plan(name=None, instance_type=None, vcpu=None, ram_gb=None, disk_gb=8, ticket=None):
    """Read-only preview of a new server. Creates nothing."""
    if not name:
        return _fail("name is required")
    sess = _sess()
    itype = instance_type
    if not itype:
        if not (vcpu and ram_gb):
            return _fail("give an instance_type, or vcpu and ram_gb")
        itype = gr.find_type(sess, int(vcpu), float(ram_gb))
        if not itype:
            return _fail("no current-generation type has %s vCPU and %s GB" % (vcpu, ram_gb))
    it = sess.client("ec2").describe_instance_types(InstanceTypes=[itype])["InstanceTypes"][0]
    cpus = it["VCpuInfo"]["DefaultVCpus"]
    if gr.MAX_VCPU and cpus > gr.MAX_VCPU:
        return _fail("%s has %d vCPU; this environment allows at most %d" % (itype, cpus, gr.MAX_VCPU))
    disk = int(disk_gb or 8)
    if not 8 <= disk <= 1000:
        return _fail("disk must be 8-1000 GB")
    plan = {"name": name, "instance_type": itype, "vcpu": cpus, "ram_gb": round(it["MemoryInfo"]["SizeInMiB"] / 1024, 1), "disk_gb": disk,
            "environment": gr.ENV, "ami": "latest Amazon Linux 2023", "subnet": os.environ.get("SUBNET_ID", "NOT SET"),
            "security_group": os.environ.get("SECURITY_GROUP_ID", "NOT SET"), "instance_profile": os.environ.get("INSTANCE_PROFILE", "NOT SET"),
            "access": "SSM only, no SSH, IMDSv2, encrypted gp3 disk"}
    _note(_rec(ticket), "Deployment plan: " + json.dumps(plan))
    return {"ok": True, "plan": plan}


@_safe
def deployment_apply(name=None, instance_type=None, vcpu=None, ram_gb=None, disk_gb=8, change_number=None, approved=False,
                     requested_by="MATRIX"):
    """Create the server from the plan (uses matrix_guardrails.deploy_ec2)."""
    err, rec = _change(change_number, approved)
    if err:
        return err
    req = {"ticket": change_number, "name": name, "disk_gb": disk_gb, "requested_by": requested_by}
    if instance_type:
        req["instance_type"] = instance_type
    else:
        req.update(vcpu=vcpu, ram_gb=ram_gb)
    r = gr.deploy_ec2(req)
    if r.get("status") != "created":
        return _fail(r.get("message") or r)
    return {"ok": True, "instance_id": r["instance_id"], "message": r["message"], "next": "call migration_validate (it works for new servers too), then add the CI to the CMDB"}


# ----------------------------------------------------------------- decommission
@_safe
def decommission_assess(instance_id=None, ticket=None):
    """Read-only: what depends on this server, and has it been used lately?"""
    sess = _sess()
    err = _targets(sess, [instance_id])
    if err:
        return err
    i = _inst(sess, instance_id)
    ec2, cw, elb = sess.client("ec2"), sess.client("cloudwatch"), sess.client("elbv2")
    flags = []
    eips = [a["PublicIp"] for a in ec2.describe_addresses(Filters=[{"Name": "instance-id", "Values": [instance_id]}])["Addresses"]]
    if eips:
        flags.append("has Elastic IP(s) %s that would be released from it" % eips)
    in_tg = []
    for tg in elb.describe_target_groups(PageSize=50)["TargetGroups"]:
        try:
            for d in elb.describe_target_health(TargetGroupArn=tg["TargetGroupArn"])["TargetHealthDescriptions"]:
                if d["Target"]["Id"] == instance_id:
                    in_tg.append(tg["TargetGroupName"])
        except Exception:
            pass
    if in_tg:
        flags.append("is a target in load balancer group(s) %s" % in_tg)
    end = time.time()
    start = end - 14 * 86400
    cpu_max = None
    try:
        dp = cw.get_metric_statistics(Namespace="AWS/EC2", MetricName="CPUUtilization", Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                                      StartTime=start, EndTime=end, Period=86400, Statistics=["Maximum"])["Datapoints"]
        cpu_max = max([d["Maximum"] for d in dp]) if dp else None
    except Exception:
        pass
    if i["State"]["Name"] == "running" and cpu_max is not None and cpu_max > 10:
        flags.append("was busy in the last 14 days (peak CPU %.0f%%)" % cpu_max)
    backups = [im["ImageId"] for im in ec2.describe_images(Owners=["self"], Filters=[
        {"Name": "tag:matrix-source-instance", "Values": [instance_id]}, {"Name": "tag:matrix-purpose", "Values": ["final-backup"]}])["Images"]]
    res = {"name": _name(i), "instance_id": instance_id, "state": i["State"]["Name"], "peak_cpu_14d": cpu_max, "elastic_ips": eips,
           "load_balancer_groups": in_tg, "volumes": [b["Ebs"]["VolumeId"] for b in i.get("BlockDeviceMappings", []) if "Ebs" in b],
           "final_backups": backups, "warnings": flags, "safe_to_proceed": not flags}
    _note(_rec(ticket), "Decommission assessment of %s: %s" % (res["name"], json.dumps({"warnings": flags, "backups": backups})))
    return {"ok": True, "assessment": res}


@_safe
def decommission_snapshot(instance_id=None, change_number=None, approved=False):
    """Final backup AMI (includes all volumes) before anything is removed."""
    err, rec = _change(change_number, approved)
    if err:
        return err
    sess = _sess()
    err = _targets(sess, [instance_id])
    if err:
        return err
    img = _mk_image(sess, instance_id, change_number, "final-backup")
    _note(rec, "Final backup image %s created for %s." % (img, instance_id))
    _audit("decommission_snapshot", change_number, instance=instance_id, image=img)
    return {"ok": True, "image_id": img, "next": "wait until migration_image_status shows available, then decommission_stop"}


@_safe
def decommission_stop(instance_id=None, change_number=None, approved=False):
    """Stop the server (reversible). Refuses unless a final backup image is available."""
    err, rec = _change(change_number, approved)
    if err:
        return err
    sess = _sess()
    err = _targets(sess, [instance_id])
    if err:
        return err
    ec2 = sess.client("ec2")
    if not _final_backup(ec2, instance_id):
        return _fail("no available final backup image for %s. Run decommission_snapshot and wait for it first." % instance_id)
    ec2.stop_instances(InstanceIds=[instance_id])
    ok = _wait_state(ec2, instance_id, "stopped")
    msg = "%s %s. It stays stopped for %d days before it can be terminated." % (instance_id, "stopped" if ok else "is stopping", HOLD_DAYS)
    _note(rec, msg)
    _audit("decommission_stop", change_number, instance=instance_id)
    return {"ok": True, "message": msg}


def _final_backup(ec2, instance_id):
    imgs = ec2.describe_images(Owners=["self"], Filters=[{"Name": "tag:matrix-source-instance", "Values": [instance_id]},
                                                         {"Name": "tag:matrix-purpose", "Values": ["final-backup"]}])["Images"]
    return next((i["ImageId"] for i in imgs if i["State"] == "available"), None)


def _stopped_days(inst):
    m = re.search(r"\((\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) GMT\)", inst.get("StateTransitionReason", "") or "")
    if not m:
        return None
    import calendar
    return (time.time() - calendar.timegm(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))) / 86400


@_safe
def decommission_terminate(instance_id=None, change_number=None, approved=False):
    """Final removal. The normal executor role is DENIED terminate by design. This uses DECOMMISSION_ROLE_ARN
    (optional stack parameter) and only works when ALL of these are true:
      stopped for >= DECOM_HOLD_DAYS, a final backup image is available, a human has added the tag
      decommission-approved=true to the instance in the console, and the change is approved."""
    err, rec = _change(change_number, approved)
    if err:
        return err
    sess = _sess()
    err = _targets(sess, [instance_id])
    if err:
        return err
    i = _inst(sess, instance_id)
    tags = {t["Key"]: t["Value"] for t in i.get("Tags", [])}
    if i["State"]["Name"] != "stopped":
        return _fail("%s must be stopped first (state: %s)" % (instance_id, i["State"]["Name"]))
    days = _stopped_days(i)
    if days is None or days < HOLD_DAYS:
        return _fail("%s has not been stopped for %d days yet (%s)" % (instance_id, HOLD_DAYS, "unknown" if days is None else "%.1f days" % days))
    backup = _final_backup(sess.client("ec2"), instance_id)
    if not backup:
        return _fail("no available final backup image for %s" % instance_id)
    if tags.get("decommission-approved") != "true":
        return _fail("a human must add the tag decommission-approved=true to %s in the AWS console before it can be terminated" % instance_id)
    if not DECOM_ROLE:
        return _fail("terminate is not enabled in this account (DECOMMISSION_ROLE_ARN is not set). Terminate %s by hand; backup image is %s" % (instance_id, backup))
    c = boto3.client("sts", region_name=gr.REGION).assume_role(RoleArn=DECOM_ROLE, RoleSessionName=re.sub(r"[^\w=,.@-]", "", change_number)[:60],
                                                               DurationSeconds=900)["Credentials"]
    s2 = boto3.Session(aws_access_key_id=c["AccessKeyId"], aws_secret_access_key=c["SecretAccessKey"], aws_session_token=c["SessionToken"], region_name=gr.REGION)
    s2.client("ec2").terminate_instances(InstanceIds=[instance_id])
    msg = "%s terminated. Backup image kept: %s." % (instance_id, backup)
    _note(rec, msg)
    _audit("decommission_terminate", change_number, instance=instance_id, backup=backup)
    return {"ok": True, "message": msg, "next": "retire the CI with snow_update_cmdb_ci (install_status=retired)"}


# names used by matrix_ops_install.py
SKILLS = ["patch_scan", "patch_status", "patch_install", "migration_assess", "migration_replicate", "migration_image_status",
          "migration_copy_image", "migration_launch", "migration_validate", "migration_cutover", "migration_rollback",
          "deployment_plan", "deployment_apply", "decommission_assess", "decommission_snapshot", "decommission_stop",
          "decommission_terminate"]
