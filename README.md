# Madeira

This is a python package which provides wrapper classes for 
Amazon Web Servces (AWS) python deployment SDK (`boto3`).

In several deployment automation projects I've built over the years,
I've found that "bare metal control" over interaction with AWS services
allows me to leverage features released by AWS into `boto3` the moment
they're available, rather than waiting on 3rd party CM tool authors/vendors
to wrap *all* required functionality.

Given that most projects I work on are "pure python", this approach requires
less mental context switching compared to using template-driven CM tools. 

## Installation

This package is hosted on [PyPI](pypi.org), so you may simply:

```
pip install --user madeira
```

## Support

Intended for use with Python 3.7 or later.

## Package name origins

Since the AWS python SDK is called `boto`, which refers to Amazon River dolphins,
I figured I'd attempt to follow the pattern and name this after a tributary of the 
Amazon River, given that the point of these wrappers is to deploy objects into AWS,
The analogy seemed to solve the problem of developer naming creativity...
:stuck_out_tongue_winking_eye: