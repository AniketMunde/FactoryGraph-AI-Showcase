# Phase 4 modeling and feasibility decisions — 2026-11-12

Use an event-centric property graph over the exact pinned Microsoft tables. Keep dense
telemetry in existing Parquet. ComponentType is a source category, never a physical part.
Stable source-row identities preserve simultaneous distinct records. Exact duplicate keys
remain invalid; maintain separate maintenance/failure facts and mark derived exact-key
matches, with no physical double-count or invented cause.

Neo4j Community **5.26.33 LTS** is pinned rather than selecting a database on query results.
The [official deployment center](https://neo4j.com/deployment-center/) identifies the release;
the [5.x requirements](https://neo4j.com/docs/operations-manual/5/installation/requirements/)
support Windows11 development with Java17/21. The minimal compatible Zulu JRE21 runtime
is used because the official requirements permit a JRE. Docker/Java/Neo4j were absent on
PATH; download official ZIPs into ignored project data, without changing system settings
or installing a Windows service. Verify publisher SHA-256 metadata before extraction.

The actual server archive NOTICE/LICENSE declares **GPLv3** with bundled third-party
notices. The official driver **6.4.1** package declares Apache-2.0 and marked PSF-licensed
pieces, with Python>=3.10. See [driver installation/compatibility](https://neo4j.com/docs/python-manual/current/install/)
and [upstream driver notice](https://github.com/neo4j/neo4j-python-driver/blob/6.x/LICENSE.txt).
The 6.x driver supports 5.x servers; verify this combination with actual integration.
No paid edition, Aura account, proprietary graph algorithm, APOC or GDS is required.
Redistribution must respect each upstream license; this is a local research installation,
not a grant of a publication license to FactoryGraph itself.

Authentication stays enabled. Bind Bolt only to 127.0.0.1:17687, disable HTTP/HTTPS, use
768MiB maximum heap and 256MiB page cache. Credentials come through environment variables;
an optional ignored local secret file initializes the development session. No password
belongs in config, logs, reports, fixtures or source control. Use a dedicated runtime and
namespaces; resets must name the project namespace and verify its owned build marker.

Historical visibility uses event time strictly before cutoff, with immediate availability
explicitly assumed because source recorded/available timestamps do not exist. Measured
2026 ingestion time is provenance only. Static model/age assumptions match Phase1.
Research artifact references are verified catalog lineage excluded from historical queries.
All peer events require cutoff predicates; sharing a model is not a physical dependency.

Features are deterministic aggregations of graph-retrieved source facts, with vectorized
temporal prefix calculations rather than hundreds of thousands of network round trips.
Independent Parquet/Pandas masks validate equivalent counts. This is not a claim that
the aggregations require graphs or add information absent from relational sources.
Existing tabular error/maintenance history is conceptually redundant; additional windows
and model-peer context are explicit candidate features, untested for predictive value.

Separate Phase4 dependencies preserve every accepted environment/lock. Keep failed setup
evidence and distinguish runtime acquisition/installation from genuine server integration.
The first Azul checksum URL attempt returned404; the official package metadata API supplied
the publisher SHA-256. Local PowerShell script execution is disabled, so reproducible
commands use inline environment assignment and the official Java CLI, without changing
execution policy. No failure of the prior Chronos MetroPT test is repaired in this phase.
