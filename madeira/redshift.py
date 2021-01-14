import boto3


class Redshift(object):
    def __init__(self):
        self.redshift_client = boto3.client('redshift')

    def get_clusters(self):
        return self.redshift_client.describe_clusters()
