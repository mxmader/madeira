import base64
import hashlib
import io
import logging
import os
import sys

import requests
import zipfile

__version__ = '1.0.12'

aws_profile = None
region_name = None


# TODO: logging throughout (move to class)

# TODO: move to an IAM class
def get_account_arn(account_id):
    return f'arn:aws:iam::{account_id}:root'


def get_base64_digest(hash_object):
    return base64.b64encode(hash_object.digest()).decode("utf-8")


def get_base64_sum_of_file(file, hash_type='sha256'):
    hash_object = get_hash_object(hash_type)
    with open(file, 'rb') as f:
        while True:
            data = f.read(65536)
            if not data:
                break
            hash_object.update(data)
    return get_base64_digest(hash_object)


def get_base64_sum_of_data(data, hash_type='sha256'):
    hash_object = get_hash_object(hash_type)
    hash_object.update(data)
    return get_base64_digest(hash_object)


def get_base64_sum_of_stream(stream, hash_type='sha256', block_size=1048576):
    hash_object = get_hash_object(hash_type)
    while True:
        buffer = stream.read(block_size)
        if not buffer:
            break
        hash_object.update(buffer)
    return get_base64_digest(hash_object)


def get_base64_sum_of_file_in_zip_from_url(url, file_name_in_zip, hash_type='sha256'):
    r = requests.get(url)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    return get_base64_sum_of_data(z.read(file_name_in_zip), hash_type=hash_type)


def get_hash_object(hash_type):
    hash_function = getattr(hashlib, hash_type)
    return hash_function()


def get_logger(level=logging.INFO, use_stdout=True, logger_name='app_logger'):
    logger = logging.getLogger(logger_name)

    # only override the logger-scoped level if we're making it more granular with this particular invocation
    if not logger.level or level < logger.level:
        logger.setLevel(level)

    # if we already have a handler, we're likely calling get_logger for the Nth time within a given process.
    if use_stdout and not logger.handlers:
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


def set_profile(profile, region=None):
    """Set the credential profile for the AWS SDK to use."""
    global aws_profile
    aws_profile = profile
    os.environ['AWS_PROFILE'] = profile
    if region:
        global region_name
        region_name = region
        os.environ['AWS_DEFAULT_REGION'] = region
