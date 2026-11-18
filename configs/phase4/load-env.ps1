# Dot-source after setting secrets in the session, or use the ignored local credential file.
# No credential values are emitted to the console.
if (-not $env:FACTORYGRAPH_NEO4J_PASSWORD) {
    if (-not (Test-Path -LiteralPath '.env.phase4')) {
        throw 'Set FACTORYGRAPH_NEO4J_PASSWORD or create the ignored .env.phase4 locally.'
    }
    $env:FACTORYGRAPH_NEO4J_PASSWORD = (Get-Content -LiteralPath '.env.phase4' -Raw).Trim()
}
$env:FACTORYGRAPH_NEO4J_USER = 'neo4j'
$env:FACTORYGRAPH_NEO4J_URI = 'bolt://127.0.0.1:17687'
