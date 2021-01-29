import base64
import json
import random
import string

from madeira import session
from madeira_utils import loggers


class SecretsManager(object):

    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else loggers.get_logger()
        self._session = session.Session(logger=logger, profile_name=profile_name, region=region)

        self.secrets_manager_client = self._session.session.client(service_name="secretsmanager")

    @staticmethod
    def generate_clean_password(size=32, chars=string.ascii_letters + string.digits):
        """Generates a password free of special characters."""
        return "".join(random.choice(chars) for _ in range(size))

    def get_secret(self, secret_name):

        try:
            get_secret_value_response = self.secrets_manager_client.get_secret_value(SecretId=secret_name)
        except self.secrets_manager_client.exceptions.ResourceNotFoundException:
            self._logger.error("%s: secret does not exist", secret_name)
            return None

        if "SecretString" in get_secret_value_response:
            secret = json.loads(get_secret_value_response.get("SecretString", "{}"))
        else:
            secret = base64.b64decode(get_secret_value_response["SecretBinary"])

        return secret

    def store_secret(self, secret_name, secret_description, secret):
        return self.secrets_manager_client.create_secret(
            Name=secret_name,
            Description=secret_description,
            SecretString=json.dumps(secret),
        )

    def update_secret(self, secret_name, secret):
        return self.secrets_manager_client.update_secret(
            SecretId=secret_name,
            SecretString=json.dumps(secret),
        )
