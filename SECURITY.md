# Security scope and reporting

FactoryGraph is a native, retrospective research demonstration. It is not validated for
operational machinery decisions and no supported public service is provided here.

The clients use an authenticated FastAPI boundary. Credentials remain server-side;
input, object authorization, rate, concurrency and historical-cutoff checks apply.
The local roles are not a production identity service. Neo4j application read-query
restrictions are not database-enforced read-only RBAC in Community Edition.

Do not put credentials, source data, private case JSON, logs or recordings in public
issues. Arrange a private reporting channel with the maintainer before sharing sensitive
reproduction material. No response SLA or vulnerability-free/compliance certification is
claimed. Supported testing scope and prerequisites are in docs/VALIDATION.md.

Full mode requires authorized registered research artifacts. Gallery mode requires
authorized saved cases. Missing dependencies never select the illustrative software
fixture. Keep real .env files, credentials, data stores and model caches out of Git.
