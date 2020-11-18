import madeira
from madeira import secrets_manager
import psycopg2.extras


class Postgres(object):

    def __init__(self, credentials, init_cursors=True, logger=None, region_name=None):
        self._logger = logger if logger else madeira.get_logger()

        if isinstance(credentials, dict):
            self._logger.debug('Using DB creds dict as-is')
            self.credentials = credentials
        else:
            self._logger.debug(f'Fetching DB creds from AWS Secrets Manager using ID: {credentials}')
            secrets_manager_wrapper = secrets_manager.SecretsManager(logger=logger, region_name=region_name)
            self.credentials = secrets_manager_wrapper.get_secret(credentials)

        self.connection = None
        self.read_cursor = None
        self.write_cursor = None

        if init_cursors:
            self.init_cursors()

    # uses a larger default page_size than psycopg2
    def bulk_insert(self, insert_query, data, template=None, page_size=1000):
        psycopg2.extras.execute_values(self.write_cursor, insert_query, data,
                                       template=template, page_size=page_size)

    def bulk_update(self, update_query, data):
        self.write_cursor.executemany(update_query, data)

    def create_db(self, db_name):
        try:
            self.write_cursor.execute(f'CREATE DATABASE "{db_name}"')
            self._logger.info(f'Created database {db_name}')
        except psycopg2.errors.DuplicateDatabase:
            self._logger.info(f'Database {db_name} already exists')
            pass

    def drop_db(self, db_name):
        self.write_cursor.execute(f'DROP DATABASE IF EXISTS {db_name}')
        self._logger.info(f'Dropped database {db_name}')

    def get_cursor(self, mode='readonly'):
        if not self.connection:
            self.connection = psycopg2.connect(
                dbname=self.credentials['dbname'],
                host=self.credentials['host'],
                port=self.credentials['port'],
                user=self.credentials['username'],
                password=self.credentials['password'],

                # this should remain sufficiently high in order to allow platforms like Aurora sufficient time
                # to spin listeners up from a quiesced state
                connect_timeout=30)

        if mode == 'readonly':
            self.connection.set_session(readonly=True)

        self.connection.set_session(autocommit=True)
        return self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def get_sqlalchemy_url(self):
        return 'postgres://{username}:{password}@{host}:{port}/{dbname}'.format(
            username=self.credentials['username'],
            password=self.credentials['password'],
            host=self.credentials['host'],
            port=self.credentials['port'],
            dbname=self.credentials['dbname']
        )

    def get_readonly_query_results(self, query, params=None, cursor=None):
        if not cursor:
            cursor = self.read_cursor

        cursor.execute(query, params)
        return cursor.fetchall()

    def get_count_results(self, query, params=None):
        self.read_cursor.execute(query, params)
        return self.read_cursor.fetchone().get('count')

    def init_cursors(self):
        if self.read_cursor:
            self.read_cursor.close()
        self.read_cursor = self.get_cursor()

        if self.write_cursor:
            self.write_cursor.close()
        self.write_cursor = self.get_cursor(mode='write')
