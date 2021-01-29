import configparser
import os
import uuid

from madeira import session
from madeira_utils import loggers


class Sts(object):
    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else loggers.get_logger()
        self._session = session.Session(profile_name=profile_name, region=region)
        self.sts_client = self._session.session.client("sts")

        # for convenience
        sts_caller_identity = self.sts_client.get_caller_identity()
        self.account_id = sts_caller_identity.get("Account")
        self.user_arn = sts_caller_identity.get("Arn")
        self.user_id = sts_caller_identity.get("UserId")

    def get_access_keys(self, duration=3600):
        token = self.sts_client.get_session_token(DurationSeconds=duration).get(
            "Credentials"
        )
        return (
            token.get("AccessKeyId"),
            token.get("SecretAccessKey"),
            token.get("SessionToken"),
        )

    def write_role_credentials(self, aws_profile, role_arn, role_session_name=None, duration=None):
        role_session_name = role_session_name if role_session_name else uuid.uuid4().hex
        creds = self.sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName=role_session_name,
            DurationSeconds=duration)
        aws_creds_file = os.path.expanduser("~/.aws/credentials")

        # update the AWS credentials file
        config = configparser.ConfigParser()
        config.read(aws_creds_file)

        if aws_profile not in config:
            config[aws_profile] = {}

        config[aws_profile] = {
            "region": "us-east-1",
            "aws_access_key_id": creds["Credentials"]["AccessKeyId"],
            "aws_secret_access_key": creds["Credentials"]["SecretAccessKey"],
            "aws_session_token": creds["Credentials"]["SessionToken"],
        }

        with open(aws_creds_file, "w") as configfile:
            config.write(configfile)
