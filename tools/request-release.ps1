param(
    [ValidateSet('Request', 'Publish')][string]$Action = 'Request',
    [string]$SourceSha,
    [string]$Version,
    [string]$CandidateTag,
    [switch]$AllowUnsignedWindows,
    [switch]$Publish
)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw 'GitHub CLI가 필요합니다.' }
if ($Action -eq 'Request') {
    if ($SourceSha -cnotmatch '^[a-f0-9]{40}$') { throw '검토한 main 커밋의 전체 SHA를 지정하세요.' }
    if ($Version -notmatch '^\d+\.\d+\.\d+(?:\.dev\d+)?$') { throw '소스의 새 버전을 지정하세요.' }
    if ($Publish) { throw '-Publish는 -Action Publish에서만 사용할 수 있습니다.' }
    if (-not $AllowUnsignedWindows) { throw '현재 개발판은 Windows Authenticode 미서명입니다. -AllowUnsignedWindows로 명시적으로 확인하세요.' }
    & gh workflow run release.yml --repo misosiruda/bongo-cat-chat-release --ref main -f "source_sha=$SourceSha" -f "version=$Version" -F allow_unsigned_windows=true
    if ($LASTEXITCODE -ne 0) { throw '배포 후보 요청에 실패했습니다.' }
    Write-Output 'Windows Authenticode 미서명 개발판 빌드를 요청했습니다. 빌드 결과와 파일 해시를 확인하고 release-signing을 직접 승인하세요.'
    Write-Output 'https://github.com/misosiruda/bongo-cat-chat-release/actions/workflows/release.yml'
} else {
    if ($CandidateTag -notmatch '^approved-v\d+\.\d+\.\d+(?:\.dev\d+)?-[1-9]\d*-[1-9]\d*$') { throw '성공한 서명 작업의 approved 태그를 지정하세요.' }
    $dryRun = if ($Publish) { 'false' } else { 'true' }
    & gh workflow run publish-approved-release.yml --repo misosiruda/bongo-cat-chat --ref main -f "candidate_tag=$CandidateTag" -F "dry_run=$dryRun"
    if ($LASTEXITCODE -ne 0) { throw '검증 또는 게시 요청에 실패했습니다.' }
    Write-Output "요청 완료: dry_run=$dryRun. 실제 게시는 release-publishing 승인이 필요합니다."
    Write-Output 'https://github.com/misosiruda/bongo-cat-chat/actions/workflows/publish-approved-release.yml'
}
