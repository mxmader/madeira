import madeira
import base64
import boto3
import json
import random
import string


# All AWS SDK calls presume that ~/.aws/credentials has been pre-configured and uses an
# access key with appropriate permissions via attached IAM roles + policies
class SecretsManager(object):

    def __init__(self, logger=None, region_name=None):
        self._logger = logger if logger else madeira.get_logger()
        self.secrets_manager_client = boto3.session.Session().client(
            service_name="secretsmanager", region_name=region_name
        )

    @staticmethod
    def generate_clean_password(size=32, chars=string.ascii_letters + string.digits):
        """Generates a password free of special characters."""
        return "".join(random.choice(chars) for _ in range(size))

    def get_secret(self, secret_name):
        # TODO: raises botocore.exceptions.ClientError
        get_secret_value_response = self.secrets_manager_client.get_secret_value(SecretId=secret_name)

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
