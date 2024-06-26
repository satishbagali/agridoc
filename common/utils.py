import logging, json, certifi, re, uuid, base64, regex
from peewee import DoesNotExist
from requests import Request, Session
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from common.constants import Constants
from database.db_operations import create_record, get_record_by_field, update_record
from database.database_config import db_conn
from database.models import Conversation, Messages, User, FollowUpQuestion, Language
from django_core.config import Config
from django_core import celery
from language_service.translation import *

logger = logging.getLogger(__name__)


def send_request(
    url, headers={}, data=None, content_type="form-data", request_type="GET", total_retry=10, params=None
):
    response = None
    try:
        if content_type == "JSON":
            headers["Content-Type"] = "application/json"
            data = json.dumps(data)

        request_obj = Request(request_type, url, data=data, headers=headers, params=params)
        session = Session()
        request_prepped = session.prepare_request(request_obj)
        retries = Retry(
            total=total_retry,
            backoff_factor=0.1,
            status_forcelist=[403, 502, 503, 504],
            allowed_methods={"GET", "POST", "PUT"},
        )
        session.mount(url, HTTPAdapter(max_retries=retries))
        response = session.send(
            request_prepped,
            stream=True,
            verify=certifi.where(),
            # verify=False,
        )

        print(
            {
                "function": "send_request",
                "response_status": response.status_code,
                "url": url,
            }
        )

    except Exception as error:
        logger.error(error, exc_info=True)

    return response


def get_or_create_latest_conversation(conversation_data: dict) -> Conversation:
    conversation = None
    user_id = conversation_data.get("user_id", None)
    try:
        with db_conn:
            conversation_qs = (
                Conversation.select()
                .where(Conversation.user_id == user_id)
                .order_by(Conversation.created_on.desc())
                # .get()
            )

        conversation = conversation_qs.get() if len(conversation_qs) >= 1 else None
        if not conversation:
            conversation = create_record(Conversation, conversation_data)
            logger.info(f"New conversation created for user_id:{user_id}")

    except Exception as error:
        logger.error(error, exec_info=True)

    return conversation


def get_user_chat_history(user_id, window=Config.CHAT_HISTORY_WINDOW):
    chat_history = None
    if celery.db_conn:
        db_to_connect = celery.db_conn
    else:
        db_to_connect = db_conn
    with db_to_connect:
        conversation = get_or_create_latest_conversation({"user_id": user_id})
        messages = (
            Messages.select()
            .where(
                Messages.conversation_id == conversation.id,
                Messages.is_deleted == False,
                Messages.translated_message != None,
                Messages.message_response != None,
            )
            .order_by(Messages.created_on.desc())
            .limit(window)
        )
        chat_history = ""
        for message in reversed(messages):
            chat_history = (
                chat_history + f"\n\nUser : {message.translated_message}\nAI Assistant : {message.message_response}"
            )
        # history.append((message.translated_message, message.message_response))

    # logger.info(f"User chat history :\n {chat_history}")
    # print(f"\n ######## USER CHAT HISTORY BEGINS ########\n{chat_history} ######## USER CHAT HISTORY END ########\n")
    return chat_history


def insert_message_record(
    message_data: dict,
) -> Messages:
    message_inserted, message_id, conversation_id = None, None, None
    try:
        conversation_id = message_data.get("conversation_id")
        message_inserted = create_record(Messages, message_data)
        message_id = message_inserted.id
    except Exception as error:
        logger.error(error, exc_info=True)

    logger.info(f"Message inserted, message_id:{message_id} for conversation_id:{conversation_id}")
    return message_inserted


def get_message_object_by_id(
    message_id,
) -> Messages:
    message = get_record_by_field(Messages, "id", message_id)
    return message


def get_or_create_user_by_email(user_data: dict) -> User:
    user_obj = None
    email_id = user_data.get("email", None)
    try:
        with db_conn:
            user_obj = (
                User.get(User.email == email_id)
                # .where(User.email == email_id)
                # .get()
            )
    except DoesNotExist:
        user_obj = create_record(User, user_data)

        logger.info(f"New User created for the email_id:{email_id}")

    return user_obj


def create_follow_up_questions(data) -> FollowUpQuestion:
    # def insert_many_objects(data, ModelName):
    # with database_config.db:
    inserted_objs = None
    if celery.db_conn:
        db_to_connect = celery.db_conn
    else:
        db_to_connect = db_conn

    with db_to_connect:
        inserted_objs = FollowUpQuestion.insert_many(data).execute()

    return inserted_objs


#### TBD: Move DB queries outside this module
async def postprocess_and_translate_query_response(
    original_response, input_language, message_id, with_db_config=Config.WITH_DB_CONFIG
):
    final_response = ""
    questions = ""
    resource_message_text = ""
    resource_translation = ""
    translated_response = ""
    follow_up_question_options = []
    follow_up_question_data_to_insert = []

    try:
        output_language = input_language.split("-")[0] if "-" in input_language else input_language
        split_string_list = [
            "Example Questions:\n",
            "Here are a few questions that may help:",
            "Here are a few follow-up questions that may help:",
            "**Example Questions:**",
            "As follow-up questions, users can ask:",
            "As follow-up questions, you can ask:",
            "As follow-up questions, here are some examples based on the context provided:",
        ]
        index = -1
        if original_response:
            for substring in split_string_list:
                index = original_response.find(substring)
                if index != -1:
                    string_index = split_string_list.index(substring)
                    (final_response, questions) = original_response.split(split_string_list[string_index])
                    final_response = final_response.strip()
                    questions = questions.strip()
                    break

        if index != -1:
            translated_response = (
                await a_translate_to(final_response, output_language)
                if input_language != Constants.LANGUAGE_SHORT_CODE_ENG
                else final_response
            )

            translated_response += (
                await a_translate_to(Constants.HERE_ARE_FOLLOW_UP_QUESTIONS_TO_ASK_TEXT, output_language)
                if input_language != Constants.LANGUAGE_SHORT_CODE_ENG
                else Constants.HERE_ARE_FOLLOW_UP_QUESTIONS_TO_ASK_TEXT
            )

            key = 0
            for question in questions.split("\n")[:3]:
                final_response += f"{question}\n"
                translated_question = (
                    await a_translate_to(f"{question}\n", output_language)
                    if input_language != Constants.LANGUAGE_SHORT_CODE_ENG
                    else f"{question}\n"
                )

                translated_response += translated_question

                key += 1
                follow_up_question_id = uuid.uuid4()
                follow_up_question_text = re.sub("[1-3]\.\s*", "", str(translated_question).strip(), count=1)
                follow_up_question_options.append(
                    {
                        "id": str(follow_up_question_id),
                        "name": str(key),
                        "question": follow_up_question_text,
                    }
                )

                # append insertion data or saving of questions in FollowUpQuestion table
                follow_up_question_data_to_insert.append(
                    {
                        "id": follow_up_question_id,
                        "message": follow_up_question_text,
                        "ref_id": message_id,
                        "follow_up_question_type": "message",
                        "sequence": key,
                    }
                )

            # insert data in FollowUpQuestion table
            if len(follow_up_question_data_to_insert) > 1 and with_db_config:
                create_follow_up_questions(follow_up_question_data_to_insert)

        else:
            # if original_response does not have "Example Questions:\n" translate original_response as it is
            final_response = original_response
            translated_response = (
                await a_translate_to(final_response, output_language)
                if input_language != Constants.LANGUAGE_SHORT_CODE_ENG
                else final_response
            )

    except Exception as error:
        logger.error(error, exc_info=True)

    return (
        translated_response,
        final_response,
        follow_up_question_options,
        follow_up_question_data_to_insert,
    )


def save_message_obj(message_id, message_data_to_insert_or_update):
    # with db_conn:
    # message_obj.save()
    update_record(Messages, message_id, message_data_to_insert_or_update)


def clean_text(text):
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Remove Markdown links and images
    text = re.sub(r"!\[[^\]]*\]\([^\)]*\)", "", text)  # Images
    text = re.sub(r"\[[^\]]*\]\([^\)]*\)", "", text)  # Links
    text = text.replace("*", "").replace("_", "")

    # Remove any remaining special characters except new lines
    # This regex keeps letters (including non-English), digits, and new lines
    # text = re.sub(r'[^\p{L}\p{M}\p{N}\p{Z}\s\n]', '', text, flags=re.UNICODE)
    text = regex.sub(r"[^\p{L}\p{M}\p{N}\p{Z}\s\n]", "", text, flags=regex.UNICODE)

    return text


def encode_binary_to_base64(audio_file):
    base64_string = None
    try:
        with open(audio_file, "rb") as audio_file_buffer:
            audio_binary_data = audio_file_buffer.read()
            base64_string = base64.b64encode(audio_binary_data).decode()

    except Exception as error:
        logger.error(error, exc_info=True)

    return base64_string


def decode_base64_to_binary(base64_string):
    binary_file = None
    try:
        binary_file = base64.b64decode(base64_string)
    except Exception as error:
        logger.error(error, exc_info=True)

    return binary_file


def get_language_by_code(code: str) -> Language:
    language = None
    if celery.db_conn:
        db_to_connect = celery.db_conn
    else:
        db_to_connect = db_conn
    with db_to_connect:
        try:
            language = Language.get(Language.code == code)
        except DoesNotExist:
            logger.info(f"Exception, Language by code {code} does not exists")
    return language
