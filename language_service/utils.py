import logging

from database.models import Language
from database.database_config import db_conn
from database.db_operations import get_record_by_field

logger = logging.getLogger(__name__)


def get_all_languages() -> list:
    language_list = []

    try:
        with db_conn:
            language_query = Language.select(
                Language.id, Language.name, Language.display_name, Language.code, Language.latn_code, Language.bcp_code
            ).where(Language.is_deleted == False)

            if language_query.count() >= 1:
                language_list = list(language_query.dicts().execute())

    except Exception as error:
        logger.error(error, exc_info=True)

    return language_list


def get_language(language_id):
    language = []
    try:
        with db_conn:
            language_query = Language.select(
                (Language.id).alias("language_id"), Language.name, Language.display_name
            ).where(Language.is_deleted == False, Language.id == language_id)

            if language_query.count() >= 1:
                language = list(language_query.dicts().execute())[0]

    except Exception as error:
        logger.error(error, exc_info=True)

    return language
