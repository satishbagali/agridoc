import asyncio, logging, json, datetime, os, uuid

from common.constants import Constants
from common.utils import (
    decode_base64_to_binary,
    encode_binary_to_base64,
    get_user_chat_history,
    get_message_object_by_id,
    get_or_create_latest_conversation,
    get_or_create_user_by_email,
    insert_message_record,
    postprocess_and_translate_query_response,
    save_message_obj,
    send_request,
)
from database.models import User
from database.database_config import db_conn
from database.db_operations import update_record
from django_core.config import Config
from rag_service.execute_rag import execute_rag_pipeline
from language_service.translation import detect_language_and_translate_to_english, a_translate_to
from language_service.asr import transcribe_and_translate
from language_service.tts import synthesize_speech


logger = logging.getLogger(__name__)


def authenticate_user_based_on_email(email_id):
    authenticated_user = None
    try:
        # user_obj = get_record_by_field(User, "email", email_id)
        authentication_url = f"{Config.CONTENT_DOMAIN_URL}{Config.CONTENT_AUTHENTICATE_ENDPOINT}"
        response = send_request(
            authentication_url, data={"email": email_id}, content_type="JSON", request_type="POST", total_retry=3
        )
        authenticated_user = json.loads(response.text) if response and response.status_code == 200 else None

    except Exception as error:
        logger.error(error, exc_info=True)

    return authenticated_user


def preprocess_user_data(
    original_query,
    email_id,
    authenticated_user={},
    with_db_config=Config.WITH_DB_CONFIG,
    message_input_type=Constants.MESSAGE_INPUT_TYPE_TEXT,
):
    user_name, message_id, message_obj, user_id = None, None, None, None
    user_data, message_data_to_insert_or_update = {}, {}

    try:
        if with_db_config and len(authenticated_user) >= 1:
            # save the user if it does not exist in the system
            user_obj = get_or_create_user_by_email(
                {
                    "id": authenticated_user.get("id"),
                    "email": email_id,
                    "phone": authenticated_user.get("phone_number", None),
                    "first_name": authenticated_user.get("first_name", None),
                    "last_name": authenticated_user.get("last_name", None),
                }
            )
            user_id = user_obj.id
            user_name = user_obj.first_name

            conversation_obj = get_or_create_latest_conversation({"user_id": user_id, "title": original_query})
            message_obj = insert_message_record(
                {"original_message": original_query, "conversation_id": conversation_obj}
            )
            message_id = message_obj.id
            message_data_to_insert_or_update["input_type"] = message_input_type
            message_data_to_insert_or_update["message_input_time"] = datetime.datetime.now()

            user_data.update({"user_id": user_id, "user_name": user_name, "message_id": message_id})

    except Exception as error:
        logger.error(error, exc_info=True)

    finally:
        if message_obj and message_id:
            save_message_obj(message_id, message_data_to_insert_or_update)

    return user_data, message_obj


def process_query(original_query, email_id, authenticated_user={}):
    message_obj, chat_history = None, None
    response_map, message_data_to_insert_or_update, message_data_update_post_rag_pipeline = {}, {}, {}

    try:
        user_data, message_obj = preprocess_user_data(original_query, email_id, authenticated_user)
        # fetch user chat history
        user_id = user_data.get("user_id", None)
        user_name = user_data.get("user_name", None)
        message_id = user_data.get("message_id", None)
        chat_history = get_user_chat_history(user_id) if user_id else None

        # begin translating original query to english
        message_data_to_insert_or_update["input_translation_start_time"] = datetime.datetime.now()
        query_in_english, input_language_detected = asyncio.run(
            detect_language_and_translate_to_english(original_query)
        )
        message_data_to_insert_or_update["translated_message"] = query_in_english
        message_data_to_insert_or_update["input_translation_end_time"] = datetime.datetime.now()
        message_data_to_insert_or_update["input_language_detected"] = input_language_detected
        # end of translating original query to english

        response_map, message_data_update_post_rag_pipeline = execute_rag_pipeline(
            query_in_english,
            input_language_detected,
            email_id,
            user_name=user_name,
            message_id=message_id,
            chat_history=chat_history,
        )

        # translate back to the detected input language of the original query
        # begin translating original response to input_language_detected
        (
            translated_response,
            final_response,
            follow_up_question_options,
            follow_up_question_data_to_insert,
        ) = asyncio.run(
            postprocess_and_translate_query_response(
                response_map.get("generated_final_response"), input_language_detected, str(message_id)
            )
        )
        # begin translating original response to input_language_detected

        response_map.update(
            {
                "translated_response": translated_response,
                "final_response": final_response,
                "follow_up_questions": follow_up_question_options,
            }
        )

        message_data_to_insert_or_update["message_response"] = final_response
        message_data_to_insert_or_update["message_translated_response"] = translated_response
        message_data_to_insert_or_update.update(message_data_update_post_rag_pipeline)

    except Exception as error:
        logger.error(error, exc_info=True)

    finally:
        if message_obj and message_id:
            save_message_obj(message_id, message_data_to_insert_or_update)

    return response_map


def process_input_audio_to_base64(
    original_text,
    message_id=None,
    language_code=Constants.LANGUAGE_SHORT_CODE_NATIVE,
    with_db_config=Config.WITH_DB_CONFIG,
):
    input_audio, input_audio_file = None, None

    try:
        translated_text = asyncio.run(a_translate_to(original_text, language_code))
        input_audio_file = asyncio.run(synthesize_speech(str(translated_text), language_code, message_id))
        input_audio = encode_binary_to_base64(input_audio_file)

    except Exception as error:
        logger.error(error, exc_info=True)

    finally:
        if input_audio_file:
            os.remove(input_audio_file)

    return input_audio


def process_output_audio(original_text, message_id=None, with_db_config=Config.WITH_DB_CONFIG):
    response_audio, response_audio_file, message_obj = None, None, None
    message_data_to_insert_or_update = {}

    try:
        if with_db_config and message_id:
            message_obj = get_message_object_by_id(message_id)
            input_language_detected = message_obj.input_language_detected

        else:
            query_in_english, input_language_detected = asyncio.run(
                detect_language_and_translate_to_english(original_text)
            )

        message_data_to_insert_or_update["response_text_to_speech_start_time"] = datetime.datetime.now()
        response_audio_file = asyncio.run(synthesize_speech(str(original_text), input_language_detected, message_id))
        message_data_to_insert_or_update["response_text_to_speech_end_time"] = datetime.datetime.now()

        response_audio = encode_binary_to_base64(response_audio_file)

    except Exception as error:
        logger.error(error, exc_info=True)

    finally:
        if message_obj:
            save_message_obj(message_id, message_data_to_insert_or_update)

        if response_audio_file:
            os.remove(response_audio_file)

    return response_audio


def handle_input_query(input_query):
    # if not Uploaded file, convert the base64 file string to a binary file

    input_query_file = decode_base64_to_binary(input_query)

    # store the input query file
    file_name = f"{uuid.uuid4()}_audio_input.{Constants.MP3}"
    with open(file_name, "wb") as output_file_buffer:
        output_file_buffer.write(input_query_file)

    return file_name


def process_transcriptions(
    voice_file,
    email_id,
    authenticated_user={},
    language_code=Constants.LANGUAGE_BCP_CODE_NATIVE,
    message_input_type=Constants.MESSAGE_INPUT_TYPE_VOICE,
):
    message_id, message_obj = None, None
    response_map, message_data_to_insert_or_update = {}, {}

    try:
        message_data_to_insert_or_update["message_input_time"] = datetime.datetime.now()
        message_data_to_insert_or_update["input_speech_to_text_start_time"] = datetime.datetime.now()
        transcriptions, detected_language, confidence_score = asyncio.run(
            transcribe_and_translate(voice_file, language_code)
        )

        message_data_to_insert_or_update["input_speech_to_text_end_time"] = datetime.datetime.now()
        response_map["confidence_score"] = confidence_score
        response_map["transcriptions"] = transcriptions

        if confidence_score < Constants.ASR_DEFAULT_CONFIDENCE_SCORE:
            # if confidence is less then transcriptions may not be correct
            could_not_understand_message = "Apologize! I could not understand. Please try again."
            message_data_to_insert_or_update["message_response"] = could_not_understand_message
            message_data_to_insert_or_update["message_translated_response"] = could_not_understand_message
            message_data_to_insert_or_update["message_response_time"] = datetime.datetime.now()
            message_data_to_insert_or_update["input_type"] = message_input_type
            response_map["transcriptions"] = could_not_understand_message

        user_data, message_obj = preprocess_user_data(transcriptions, email_id, authenticated_user)
        message_id = user_data.get("message_id", None)
        response_map["message_id"] = message_id

    except Exception as error:
        logger.error(error, exc_info=True)

    finally:
        if message_obj and message_id:
            save_message_obj(message_id, message_data_to_insert_or_update)

        if voice_file:
            os.remove(voice_file)

    return response_map


def get_user_by_email(email_id):
    user = None
    try:
        with db_conn:
            user_query = User.select(
                User.id, User.first_name, User.last_name, User.phone, User.preferred_language_id
            ).where(User.is_deleted == False, User.email == email_id)

            if user_query.count() >= 1:
                user = list(user_query.dicts().execute())[0]

    except Exception as error:
        logger.error(error, exc_info=True)

    return user


def set_user_preferred_language(user_id, language_id):
    saved_user_preferred_language = update_record(User, user_id, {"preferred_language_id": language_id})
    return saved_user_preferred_language
