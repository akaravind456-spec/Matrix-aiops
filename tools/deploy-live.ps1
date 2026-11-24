$ErrorActionPreference = 'Stop'
$root = 'C:\Users\Shafeeq Basha\Documents\Matrix-aiops'
$py   = Join-Path $env:TEMP 'pyemb\py\python.exe'
$aws  = 'C:\Users\Shafeeq Basha\awscli\Amazon\AWSCLIV2\aws.exe'
$zip  = Join-Path $env:TEMP 'matrix-deploy.zip'
Set-Location $root

# 1. build the zip (flat, via Python, never Set-Content)
$code = "import zipfile,glob,os,py_compile`nfor f in glob.glob('lambda/*.py'): py_compile.compile(f,doraise=True)`nz=zipfile.ZipFile(r'$zip','w',zipfile.ZIP_DEFLATED)`nfor f in glob.glob('lambda/*.py'): z.write(f,os.path.basename(f))`nz.close()"
$tmp = Join-Path $env:TEMP 'mk_zip.py'
[IO.File]::WriteAllText($tmp, $code)
& $py $tmp

# 2. deploy the Lambda and wait
& $aws lambda update-function-code --function-name matrix-console --zip-file "fileb://$zip" --profile matrix-readonly --region ap-southeast-2 --query LastUpdateStatus --output text
& $aws lambda wait function-updated --function-name matrix-console --profile matrix-readonly --region ap-southeast-2

# 3. upload the console page
& $aws s3 cp "$root\frontend\matrix-ui.html" s3://matrix-console-ui-115891591036/ --profile matrix-readonly --region ap-southeast-2 --content-type text/html

Write-Host 'DONE - tell Claude to verify.'
