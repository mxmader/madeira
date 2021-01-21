import logging
import os
import sys

__version__ = '1.0.7'

aws_profile = None
region_name = None


def set_profile(profile, region=None):
    """Set the credential profile for the AWS SDK to use."""
    global aws_profile
    aws_profile = profile
    os.environ['AWS_PROFILE'] = profile
    if region:
        global region_name
        region_name = region
        os.environ['AWS_DEFAULT_REGION'] = region


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


def get_account_arn(account_id):
    return f'arn:aws:iam::{account_id}:root'
