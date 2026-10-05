# Runtime source references

This distribution uses unmodified third-party runtime components. Full application source is provided in this repository and its matching source ZIP.

- CPython 3.12.7: https://www.python.org/ftp/python/3.12.7/Python-3.12.7.tar.xz
- PyQt6 6.7.0: https://files.pythonhosted.org/packages/ce/c6/99127e39e62f0c887a39d9644012867874a68983bd0fe641f00aa796de88/PyQt6-6.7.0.tar.gz
- Qt 6.7.3: https://download.qt.io/archive/qt/6.7/6.7.3/single/
- Python package sources: https://pypi.org/ (package names and installed versions appear in bundled .dist-info metadata and requirements files)
- spaCy English model 3.7.1: https://github.com/explosion/spacy-models/releases/tag/en_core_web_sm-3.7.1

See THIRD_PARTY_NOTICES.md, licenses/, and en_core_web_sm/LICENSES_SOURCES for copyright and license notices. Qt DLLs are dynamically linked and shipped as separate replaceable files.
