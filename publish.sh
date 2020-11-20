#!/usr/bin/env bash

set -e

# requires "wheel" and "twine" python packages
python3 setup.py sdist bdist_wheel
twine check dist/*
twine upload --repository testpypi dist/*
twine upload dist/*
