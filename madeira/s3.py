from madeira import sts
from collections import OrderedDict
from datetime import date, datetime, timedelta
import madeira
import base64
import botocore.exceptions
import boto3
import hashlib
import json


class S3(object):
    def __init__(self, logger=None):
        self.s3_client = boto3.client("s3")
        self.s3_resource = boto3.resource("s3")
        self._sts_wrapper = sts.Sts()
        self._logger = logger if logger else madeira.get_logger()

    @staticmethod
    def _get_retention_end_date(retain_years=7):
        date_today = datetime.utcnow()
        try:
            return date_today.replace(year=date_today.year + retain_years)
        except ValueError:
            return date_today + (
                date(date_today.year + retain_years, 1, 1) - date(date_today.year, 1, 1)
            )

    @staticmethod
    def _get_object_base64_md5_hash(body, blocksize=1048576):
        md5_hash = hashlib.md5()
        while True:
            buffer = body.read(blocksize)
            if not buffer:
                break
            md5_hash.update(buffer)
        digest = md5_hash.digest()
        # object checksum must be base64-encoded. See also:
        # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#S3.Client.put_object
        return base64.b64encode(digest).decode("utf-8")

    def create_folders(self, bucket_name, folders):
        # create a set of "folders" (really, a pre-provisioned set of empty objects which represent S3 object
        # prefixes) which will provide the ability for external applications (i.e. RedPoint Interaction, AWS Console)
        # to "browse" the S3 bucket as if it were a filesystem with a bunch of empty folders.
        folder_objects = self.get_folder_objects(folders)
        folder_object_keys = list(folder_objects.keys())
        for key in folder_object_keys:
            try:
                self.get_object(bucket_name, key)
                self._logger.debug(
                    "Skipping folder object: %s since it already exists", key
                )
                del folder_objects[key]
            except self.s3_client.exceptions.NoSuchKey:
                continue

        self.create_objects(bucket_name, folder_objects)

    def create_objects(self, bucket_name, objects):
        for object_key, value in objects.items():
            self._logger.info("Creating s3://%s/%s", bucket_name, object_key)
            self.s3_resource.Object(bucket_name, object_key).put(Body=value)

    def delete_object(self, bucket_name, object_key):
        self._logger.debug("Deleting s3://%s/%s", bucket_name, object_key)
        self.s3_client.delete_object(Bucket=bucket_name, Key=object_key)

    def delete_objects(self, bucket_name, object_keys):
        chunk_size = 1000
        for i in range(0, len(object_keys), chunk_size):
            chunk = object_keys[i: i + chunk_size]
            object_list = {
                "Objects": [{"Key": object_key["Key"]} for object_key in chunk],
                "Quiet": True,
            }
            self.s3_client.delete_objects(Bucket=bucket_name, Delete=object_list)
        return len(object_keys)

    def delete_object_versions(self, bucket_name, object_keys):
        chunk_size = 1000
        for i in range(0, len(object_keys), chunk_size):
            chunk = object_keys[i: i + chunk_size]
            object_list = {
                "Objects": [{"Key": object_key["Key"], "VersionId": object_key["VersionId"]} for object_key in chunk],
                "Quiet": True,
            }
            self.s3_client.delete_objects(Bucket=bucket_name, Delete=object_list, BypassGovernanceRetention=True)
        return len(object_keys)

    def does_bucket_exist(self, bucket_name):
        try:
            self.s3_resource.meta.client.head_bucket(Bucket=bucket_name)
            return True
        except botocore.exceptions.ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")

            if error_code == "403":  # bucket exists, but we don't have permissions to it
                return True
            elif error_code == "404":
                return False
            else:
                raise e

    def get_all_buckets(self):
        return [
            bucket["Name"] for bucket in self.s3_client.list_buckets().get("Buckets")
        ]

    def get_all_object_keys(self, bucket, prefix=""):
        """
        Returns all s3 keys (objects) in the named bucket as a
        list of boto.s3.key.Key objects.
        """
        paginator = self.s3_client.get_paginator("list_objects")
        page_iterator = paginator.paginate(Bucket=bucket, Prefix=prefix)
        try:
            return [
                key for page in page_iterator for key in page.get("Contents", [])
            ]
        except self.s3_client.exceptions.NoSuchBucket:
            self._logger.warning("Bucket: %s does not exist", bucket)

    def get_all_object_versions(self, bucket, prefix=""):
        """
        Returns all s3 keys (object versions) in the named bucket as a
        list of boto.s3.key.Key objects.
        """
        # seemingly, pagination wrappers don't work for "list_object_versions" even though they're supported
        object_list = []
        try:
            response = self.s3_client.list_object_versions(Bucket=bucket, Prefix=prefix)
        except self.s3_client.exceptions.NoSuchBucket:
            self._logger.warning("Bucket: %s does not exist", bucket)
            return object_list

        object_list.extend(response.get('Versions', []))
        object_list.extend(response.get('DeleteMarkers', []))

        # per https://docs.aws.amazon.com/AmazonS3/latest/dev/list-obj-version-enabled-bucket.html
        while response.get('KeyMarker') or response.get('VersionIdMarker'):
            response = self.s3_client.list_object_versions(
                KeyMarker=response['KeyMarker'], VersionIdMarker=response['VersionIdMarker'])
            object_list.extend(response.get('Versions', []))
            object_list.extend(response.get('DeleteMarkers', []))

        return object_list

    @staticmethod
    def get_folder_object_key(folder):
        return f"{folder}/.folder"

    def get_folder_objects(self, folder_list):
        """Get list of S3 'folder' object keys from a list of folders that may contain blanks, dupes, or comments."""
        folder_objects = OrderedDict()
        folder_list = sorted(folder_list)

        for folder in folder_list:
            folder = folder.strip()

            if not folder:
                continue

            if folder.startswith("#"):
                continue

            object_key = self.get_folder_object_key(folder)
            folder_objects[object_key] = ""

        return folder_objects

    def get_object(self, bucket, object_key):
        return self.s3_client.get_object(Bucket=bucket, Key=object_key)

    def get_object_contents(self, bucket, object_key, is_json=False):
        if is_json:
            return json.loads(self.get_object(bucket, object_key).get('Body').read().decode('utf-8'))

        return self.get_object(bucket, object_key).get('Body').read().decode('utf-8')

    def get_old_object_keys(self, bucket, max_age_hours=24, prefix=""):
        """
        Returns all s3 keys (objects) older than max-age hours in the named bucket as a
        list of boto.s3.key.Key objects.
        """
        past_time_at_max_age = datetime.now() - timedelta(hours=max_age_hours)
        paginator = self.s3_client.get_paginator("list_objects")
        page_iterator = paginator.paginate(Bucket=bucket, Prefix=prefix)

        bucket_object_list = []
        for page in page_iterator:
            for key in page.get("Contents", []):
                if key["LastModified"].replace(tzinfo=None) < past_time_at_max_age:
                    bucket_object_list.append(key)

        return bucket_object_list

    def get_object_md5_base64(self, bucket_name, object_key):
        source_object = self.s3_client.get_object(Bucket=bucket_name, Key=object_key)
        source_object_stream = source_object.get("Body")
        return self._get_object_base64_md5_hash(source_object_stream)

    def put_object(self, bucket_name, object_key, body, encoding="utf-8", md5=None, as_json=False):
        if as_json:
            body = json.dumps(body)
        object_args = dict(Bucket=bucket_name, Key=object_key, Body=body, ContentEncoding=encoding)
        if md5:
            object_args["ContentMD5"] = md5
        self._logger.info("Uploading s3://%s/%s", bucket_name, object_key)
        self.s3_client.put_object(**object_args)

    def rename_object(self, bucket_name, source_key, dest_key):
        self._logger.debug("Renaming %s to %s in bucket: %s", source_key, dest_key, bucket_name)
        self.s3_resource.Object(bucket_name, dest_key).copy_from(CopySource=f"{bucket_name}/{source_key}")
        self.s3_resource.Object(bucket_name, source_key).delete()

    def set_no_public_access_on_account(self):
        self._logger.info(
            "Blocking all public access attributes for all future bucket creation"
        )
        s3_control = boto3.client("s3control")
        s3_control.put_public_access_block(
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
            AccountId=self._sts_wrapper.get_account_id(),
        )

    def set_object_lock(self, bucket_name, object_key, retention_mode, retention_years):
        self._logger.info("Placing retention-based lock on: %s", bucket_name, object_key)
        return self.s3_client.put_object_retention(
            Bucket=bucket_name,
            Key=object_key,
            Retention={
                "Mode": retention_mode,
                "RetainUntilDate": self._get_retention_end_date(retention_years),
            },
        )
