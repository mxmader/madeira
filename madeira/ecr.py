import json

from madeira import session, sts
from madeira_utils import loggers


class Ecr(object):

    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else loggers.get_logger()
        self._session = session.Session(logger=logger, profile_name=profile_name, region=region)
        self._sts = sts.Sts(logger=logger, profile_name=None, region=None)

        self.ecr_client = self._session.session.client("ecr")

    def _get_registry_id_for_repo(self, repo_name):
        for repo in self.ecr_client.describe_repositories().get("repositories"):
            if repo["repositoryName"] == repo_name:
                return repo["registryId"]

    def add_account_to_repo_policy(self, secondary_account_id, repo_name):
        registry_id = self._get_registry_id_for_repo(repo_name)

        # it is possible that there is no existing policy
        try:
            policy = json.loads(
                self.ecr_client.get_repository_policy(
                    registryId=registry_id, repositoryName=repo_name
                ).get('policyText'))
            self._logger.info("Got existing policy for repo: %s in registry: %s", repo_name, registry_id)
        except self.ecr_client.exceptions.RepositoryPolicyNotFoundException:
            self._logger.warning(
                "There no existing policy for repo: %s in registry: %s",
                repo_name,
                registry_id,
            )

            # set an empty base policy to augment hereafter
            policy = {
                "Version": "2008-10-17",
                "Statement": []
            }

        # drop any statements that already have this account referenced
        for statement in policy["Statement"]:
            if secondary_account_id in statement.get("Principal", {}).get("AWS"):
                policy["Statement"].remove(statement)

        # any principal in the secondary account can describe + retrieve images
        policy["Statement"].append(
            {
                "Effect": "Allow",
                "Principal": {"AWS": f"arn:aws:iam::{secondary_account_id}:root"},
                "Action": [
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:BatchGetImage",
                    "ecr:GetAuthorizationToken",
                    "ecr:GetDownloadUrlForLayer"
                ]
            }
        )

        self._logger.info("Setting updated repository policy to allow account: %s to access repo: %s in registry: %s",
                          secondary_account_id, repo_name, registry_id)
        self.ecr_client.set_repository_policy(
            registryId=registry_id,
            repositoryName=repo_name,
            policyText=json.dumps(policy),
        )

    def delete_images(self, repo, image_ids):
        return self.ecr_client.batch_delete_image(repositoryName=repo, imageIds=image_ids)

    def get_image_list(self, repo):
        # TODO: implement "NextToken" processing
        return self.ecr_client.list_images(repositoryName=repo, maxResults=1000).get('imageIds')
