#!/usr/bin/env bash

set -e

echo "cleaning up old builds"
rm -rf dist/ build/

# requires "wheel" and "twine" python packages
python3 setup.py sdist bdist_wheel
twine check dist/*
twine upload --repository testpypi dist/*
twine upload dist/*
