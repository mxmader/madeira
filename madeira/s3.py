from collections import OrderedDict
from datetime import date, datetime, timedelta
import json
import re

from madeira import session, sts
from madeira_utils import loggers, utils


class S3(object):
    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else loggers.get_logger()
        self._session = session.Session(logger=logger, profile_name=profile_name, region=region)
        self._sts = sts.Sts(logger=logger, profile_name=None, region=None)

        self.s3_client = self._session.session.client("s3")
        self.s3_control_client = self._session.session.client("s3control")
        self.s3_resource = self._session.session.resource("s3")

    @staticmethod
    def _get_retention_end_date(retain_years=7):
        date_today = datetime.utcnow()
        try:
            return date_today.replace(year=date_today.year + retain_years)
        except ValueError:
            return date_today + (
                date(date_today.year + retain_years, 1, 1) - date(date_today.year, 1, 1)
            )

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
        except self.s3_client.exceptions.ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")

            if error_code == "403":  # bucket exists, but we don't have permissions to it
                return True
            elif error_code == "404":
                return False
            else:
                raise e

    def get_all_buckets(self):
        return [bucket["Name"] for bucket in self.s3_client.list_buckets().get("Buckets")]

    def get_all_object_keys(self, bucket, prefix=""):
        """
        Returns all s3 keys (objects) in the named bucket as a
        list of boto.s3.key.Key objects.
        """
        paginator = self.s3_client.get_paginator("list_objects")
        page_iterator = paginator.paginate(Bucket=bucket, Prefix=prefix)
        try:
            return [key for page in page_iterator for key in page.get("Contents", [])]
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
        try:
            self._logger.debug('Loading s3://%s/%s', bucket, object_key)
            return self.s3_client.get_object(Bucket=bucket, Key=object_key)
        except self.s3_client.exceptions.NoSuchKey:
            self._logger.debug("Object not found: s3://%s/%s", bucket, object_key)
            raise

    def get_object_contents(self, bucket, object_key, is_json=False):
        object_body = self.get_object(bucket, object_key).get('Body').read().decode('utf-8')
        return json.loads(object_body) if is_json else object_body

    def get_object_md5_base64(self, bucket_name, object_key):
        try:
            source_object = self.s3_client.get_object(Bucket=bucket_name, Key=object_key)
            return utils.get_base64_sum_of_stream(source_object.get("Body"), hash_type='md5')
        except self.s3_client.exceptions.NoSuchKey:
            return ''

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

    def put_object(self, bucket_name, object_key, body, encoding="utf-8", md5=None, as_json=False,
                   content_type=None):
        if as_json:
            body = json.dumps(body)

        object_args = dict(Bucket=bucket_name, Key=object_key, Body=body, ContentEncoding=encoding)

        # user-attested object checksums must be base64-encoded for submission to S3. See also:
        # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#S3.Client.put_object
        if md5:
            object_args["ContentMD5"] = md5

        if content_type:
            object_args["ContentType"] = content_type

        self._logger.info("Uploading s3://%s/%s", bucket_name, object_key)
        return self.s3_client.put_object(**object_args)

    def rename_object(self, bucket_name, source_key, dest_key):
        self._logger.debug("Renaming %s to %s in bucket: %s", source_key, dest_key, bucket_name)
        self.s3_resource.Object(bucket_name, dest_key).copy_from(CopySource=f"{bucket_name}/{source_key}")
        self.s3_resource.Object(bucket_name, source_key).delete()
        return True

    def set_no_public_access_on_account(self):
        self._logger.info(
            "Blocking all public access attributes for all future bucket creation in account: %s", self._sts.account_id)
        return self.s3_control_client.put_public_access_block(
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
            AccountId=self._sts.account_id
        )

    def set_object_lock(self, bucket_name, object_key, retention_mode, retention_years):
        self._logger.info("Placing retention-based lock on: %s", bucket_name, object_key)
        return self.s3_client.put_object_retention(
            Bucket=bucket_name,
            Key=object_key,
            Retention={
                "Mode": retention_mode,
                "RetainUntilDate": self._get_retention_end_date(retention_years),
            }
        )

    def sync_files(self, bucket, files):
        changed_files = []
        for file in files:
            result = self.upload_asset(bucket, file['name'], file['root'])
            changed_files.append(result)
        return changed_files

    def upload_asset(self, bucket, file, root):
        key_prefix = re.sub('^assets/*', '', root)
        if key_prefix:
            key_prefix += '/'
        object_key = f"{key_prefix}{file}"
        local_path = f"{root}/{file}"
        binary = False

        if file.endswith('.html'):
            content_type = 'text/html'
        elif file.endswith('.css'):
            content_type = 'text/css'
        elif file.endswith('.js'):
            content_type = 'text/javascript'
        elif file.endswith('.ico'):
            binary = True
            content_type = 'image/x-icon'
        elif file.endswith('.png'):
            binary = True
            content_type = 'image/png'
        elif file.endswith('.jpg') or file.endswith('jpeg'):
            binary = True
            content_type = 'image/jpeg'
        else:
            content_type = 'text/plain'

        self._logger.debug("%s: processing as %s; binary=%s", local_path, content_type, binary)
        base64_md5_local = utils.get_base64_sum_of_file(local_path, hash_type='md5')
        self._logger.debug("%s: Local copy base64 md5: %s", local_path, base64_md5_local)
        base64_md5_in_s3 = self.get_object_md5_base64(bucket, object_key)
        self._logger.debug("%s: S3 object base64 md5: %s", local_path, base64_md5_in_s3)

        if base64_md5_local == base64_md5_in_s3:
            self._logger.info('Checksums of local and S3 copies of %s are identical; skipping', local_path)
            return False

        return self.put_object(
            bucket, object_key, utils.get_file_content(local_path, binary=binary), content_type=content_type)
