from madeira import session, sts
from madeira_utils import loggers


class Iam(object):

    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else loggers.get_logger()
        self._session = session.Session(logger=logger, profile_name=profile_name, region=region)
        self._sts = sts.Sts(logger=logger, profile_name=None, region=None)

        self.iam_client = self._session.session.client("iam")

    def get_role_arn(self, name):
        return f"arn:aws:iam::{self._sts.account_id}:role/{name}"
