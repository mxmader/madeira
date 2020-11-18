import boto3


class Session(object):

    def __init__(self):
        self._session = boto3.Session()

    def get_client(self, client):
        return self._session.client(client)

    def get_profile_name(self):
        return self._session.profile_name

    def get_region_name(self):
        return self._session.region_name
