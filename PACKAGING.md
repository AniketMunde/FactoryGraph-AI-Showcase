# Packaging contract

Full product use is from a Git source checkout. The Python wheel distributes importable
factorygraph modules, not configuration, Next.js, datasets, accepted artifacts or a
deployable full-stack product. Installed wheel imports are checked separately.

The Python sdist includes YAML/JSON configuration/contracts, locks, documentation,
Python source and software fixtures. The public-only MANIFEST.in correction adds JSON
config and fixture patterns. The frontend/lifecycle/deployment tree remains a Git
checkout concern. No research or model/serving implementation is changed.
Build with python -m build --no-isolation. No package is uploaded by this preparation.
