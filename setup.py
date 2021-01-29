from setuptools import find_packages, setup
import madeira

import pathlib

# The directory containing this file
HERE = pathlib.Path(__file__).parent

# The text of the README file
README = (HERE / "README.md").read_text()

setup(
    name='madeira',
    version=madeira.__version__,
    description='Common AWS operation wrappers',
    long_description=README,
    long_description_content_type="text/markdown",
    url="https://github.com/mxmader/madeira",
    author='Joe Mader',
    author_email='jmader@jmader.com',
    license="MIT",
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
    ],
    packages=find_packages(exclude=['*.tests', '*.tests.*']),
    install_requires=[
        'boto3',
        'madeira-utils'
    ]
)
