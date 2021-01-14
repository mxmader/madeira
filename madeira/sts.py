import madeira
import boto3
import configparser
import os
import uuid


class Sts(object):
    def __init__(self, logger=None, profile_name=None, region=None):
        self._session = boto3.session.Session(
            profile_name=profile_name, region_name=region
        )
        self.sts_client = self._session.client("sts")
        self._logger = logger if logger else madeira.get_logger()

    def get_account_id(self):
        return self.sts_client.get_caller_identity().get("Account")

    def get_access_keys(self, duration=3600):
        token = self.sts_client.get_session_token(DurationSeconds=duration).get(
            "Credentials"
        )
        return (
            token.get("AccessKeyId"),
            token.get("SecretAccessKey"),
            token.get("SessionToken"),
        )

    def write_role_credentials(
        self, aws_profile, role_arn, role_session_name=None, duration=None
    ):
        role_session_name = role_session_name if role_session_name else uuid.uuid4().hex
        creds = self.sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName=role_session_name,
            DurationSeconds=duration,
        )
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
