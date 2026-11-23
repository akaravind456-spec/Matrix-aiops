#!/usr/bin/env bash
# Build a COMPILED release zip for the self-hosted edition: Python files become native .so modules, so the zip has no readable source.
#
#   bash tools/build-release.sh            (needs Docker; run on the vendor's build machine, not in a customer account)
#
# Output: dist/matrix-lambda-compiled.zip   (upload this to the customer's Lambda instead of the plain .py zip)
#
# How it works: the AWS Lambda Python 3.12 build image has the same Linux and Python as the runtime, so the compiled files load there.
# Only lambda_function.py stays as text: it is a small loader that imports the compiled modules.
# Honest limit: compiled code is slower to read, not impossible. The signed licence key and the contract do the rest (see IPR-001).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p dist build-release
rm -rf build-release/*
docker run --rm -v "$PWD":/work -w /work --entrypoint bash public.ecr.aws/lambda/python:3.12 -c '
  set -e
  dnf install -y gcc gcc-c++ patchelf zip >/dev/null
  pip install --quiet nuitka==2.4.8
  cd /work/lambda
  for f in *.py; do
    [ "$f" = "lambda_function.py" ] && continue
    python -m nuitka --module "$f" --output-dir=/work/build-release --remove-output --no-pyi-file >/dev/null
  done
  cp lambda_function.py /work/build-release/
  cd /work/build-release && rm -f ../dist/matrix-lambda-compiled.zip && zip -q -r ../dist/matrix-lambda-compiled.zip .
'
echo "Built dist/matrix-lambda-compiled.zip"
echo "Test it in a dev Lambda first: run the demo cases in DEMO-001 before sending it to a customer."
