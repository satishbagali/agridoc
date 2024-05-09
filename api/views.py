import logging, asyncio, base64
from django.core.files.uploadedfile import InMemoryUploadedFile
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from api.utils import (
    authenticate_user_based_on_email,
    process_query,
    process_output_audio,
    process_transcriptions,
    handle_input_query,
    process_input_audio_to_base64,
    set_user_preferred_language,
    get_user_by_email,
)
from common.constants import Constants
from language_service.utils import get_all_languages, get_language


logger = logging.getLogger(__name__)


class ChatAPIViewSet(GenericViewSet):
    authentication_classes = []

    @action(detail=False, methods=["post"])
    def get_answer_for_text_query(self, request):
        email_id = request.data.get("email_id")
        original_query = request.data.get("query")
        response_data = {"message": None, "query": original_query, "error": False, "data": []}
        response_map = {}
        authenticated_user = None

        try:
            # check for authenticated user using email
            authenticated_user = authenticate_user_based_on_email(email_id)

            # if is_authenticated == False:
            if not authenticated_user:
                response_data["message"] = "Invalid Email ID"
                return Response(response_data, status=status.HTTP_401_UNAUTHORIZED)

            response_map = process_query(original_query, email_id, authenticated_user)

            # update actual response body
            response_data["message"] = "Successful retrieval of answer for the above query."
            response_data["message_id"] = response_map.get("message_id")
            response_data["response"] = response_map.get("translated_response")
            response_data["follow_up_questions"] = response_map.get("follow_up_questions")

        except Exception as error:
            logger.error(error, exc_info=True)
            response_data.update({"message": "Something went wrong", "error": True})

        return Response(response_data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"])
    def synthesise_audio(self, request):
        original_text = request.data.get("text")
        message_id = request.data.get("message_id")
        response_data = {"message": None, "text": original_text, "error": False, "audio": None}

        try:
            response_audio = process_output_audio(original_text, message_id)
            response_data.update({"audio": response_audio, "message": "Audio synthesis successful"})

        except Exception as error:
            logger.error(error, exc_info=True)
            response_data.update({"message": "Something went wrong", "error": True})

        return Response(response_data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"])
    def transcribe_audio(self, request):
        email_id = request.data.get("email_id")
        original_query = request.data.get("query")
        query_language_code = request.data.get("query_language_code", Constants.LANGUAGE_BCP_CODE_NATIVE)
        response_data = {
            "message": None,
            "heard_input_query": None,
            "heard_input_audio": original_query,
            "confidence_score": 0,
            "error": False,
        }
        response_map = {}
        authenticated_user = None

        try:
            # check for authenticated user using email
            authenticated_user = authenticate_user_based_on_email(email_id)

            # if is_authenticated == False:
            if not authenticated_user:
                response_data["message"] = "Invalid Email ID"
                return Response(response_data, status=status.HTTP_401_UNAUTHORIZED)

            input_query = request.FILES.get("query") if len(request.FILES) >= 1 else original_query
            if isinstance(input_query, InMemoryUploadedFile):
                input_query.seek(0)
                file_content = input_query.read()
                input_query = base64.b64encode(bytes(file_content))

            input_query_file = handle_input_query(input_query)

            response_map = process_transcriptions(input_query_file, email_id, authenticated_user, query_language_code)
            message_id = response_map.get("message_id")
            confidence_score = response_map.get("confidence_score")
            heard_input_query = response_map.get("transcriptions")
            response_data.update(
                {
                    "message": "Unfortunately unable to transcribe the above voice input query.",
                    "message_id": message_id,
                    "confidence_score": confidence_score,
                    "heard_input_query": heard_input_query,
                }
            )

            if confidence_score > Constants.ASR_DEFAULT_CONFIDENCE_SCORE:
                input_audio_base64 = process_input_audio_to_base64(heard_input_query, response_map.get("message_id"))
                response_data.update(
                    {
                        "message": "Successful transcription for above input voice query.",
                        "heard_input_audio": input_audio_base64,
                    }
                )

        except Exception as error:
            logger.error(error, exc_info=True)
            response_data.update({"message": "Something went wrong", "error": True})

        return Response(response_data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"])
    def get_answer_by_voice_query(self, request):
        email_id = request.data.get("email_id", None)
        query = request.data.get("query", None)
        query_language_code = request.data.get("query_language_code", Constants.LANGUAGE_BCP_CODE_NATIVE)
        response_data = {
            "message": None,
            "heard_input_query": None,
            "heard_input_audio": None,
            "confidence_score": 0,
            "error": False,
        }

        try:
            transcribe_response = self.transcribe_audio(request)
            transcribe_response_data = transcribe_response.data if transcribe_response.status_code == 200 else {}
            confidence_score = transcribe_response_data.get("confidence_score", None)

            if confidence_score and confidence_score > Constants.ASR_DEFAULT_CONFIDENCE_SCORE:
                updated_request_obj = request
                updated_request_obj.data.update({"query": transcribe_response_data.get("heard_input_query", None)})
                get_answer_for_text_query_response = self.get_answer_for_text_query(updated_request_obj)
                get_answer_for_text_query_response_data = (
                    get_answer_for_text_query_response.data
                    if get_answer_for_text_query_response.status_code == 200
                    else {}
                )
                response_data.update(
                    {
                        "message": get_answer_for_text_query_response_data.get("message", None),
                        "message_id": transcribe_response_data.get("message_id", None),
                        "heard_input_query": transcribe_response_data.get("heard_input_query", None),
                        "heard_input_audio": transcribe_response_data.get("heard_input_audio", None),
                        "confidence_score": transcribe_response_data.get("confidence_score", None),
                        "response": get_answer_for_text_query_response_data.get("response", None),
                        "follow_up_questions": get_answer_for_text_query_response_data.get(
                            "follow_up_questions", None
                        ),
                    }
                )
            else:
                response_data = transcribe_response_data

        except Exception as error:
            logger.error(error, exc_info=True)
            response_data.update({"message": "Something went wrong", "error": True})

        return Response(response_data, status=status.HTTP_200_OK)


class LanguageViewSet(GenericViewSet):
    authentication_classes = []

    @action(detail=False, methods=["get"])
    def languages(self, request):
        email_id = request.GET.get("email_id", None)
        response_data = {"message": None, "error": False, "language_data": []}

        try:
            # check for authenticated user using email
            authenticated_user = authenticate_user_based_on_email(email_id)

            # if is_authenticated == False:
            if not authenticated_user:
                response_data["message"] = "Invalid Email ID"
                return Response(response_data, status=status.HTTP_401_UNAUTHORIZED)

            language_list = get_all_languages()
            if len(language_list) >= 1:
                response_data.update(
                    {"message": "Successful retrieval of supported language list.", "language_data": language_list}
                )
        except Exception as error:
            logger.error(error, exc_info=True)
            response_data.update({"message": "Something went wrong", "error": True})

        return Response(response_data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"])
    def set_language(self, request):
        email_id = request.data.get("email_id", None)
        language_id = request.data.get("language_id", None)
        response_data = {"message": None, "error": False}
        saved_user_preferred_language = None

        try:
            # check for authenticated user using email
            authenticated_user = authenticate_user_based_on_email(email_id)

            # if is_authenticated == False:
            if not authenticated_user:
                response_data["message"] = "Invalid Email ID"
                return Response(response_data, status=status.HTTP_401_UNAUTHORIZED)

            if not language_id:
                response_data["message"] = "Language ID not submitted"
                return Response(response_data, status=status.HTTP_400_BAD_REQUEST)

            user = get_user_by_email(email_id)
            user_id = user.get("id")

            # verify language with language_id exists
            language_dict = get_language(language_id)

            if len(language_dict) >= 1 and language_dict["language_id"] == language_id:
                saved_user_preferred_language = set_user_preferred_language(user_id, language_id)
            else:
                response_data["message"] = f"Language with ID {language_id} does not exist."
                return Response(response_data, status=status.HTTP_400_BAD_REQUEST)

            if saved_user_preferred_language:
                response_data.update(
                    {
                        "message": f"Saved the user's ({email_id}) preferred language with {language_dict.get('display_name')}"
                    }
                )
            else:
                response_data.update(
                    {
                        "message": f"Unable to save user's ({email_id}) preferred language with {language_dict.get('display_name')}"
                    }
                )

        except Exception as error:
            logger.error(error, exc_info=True)
            response_data.update({"message": "Something went wrong", "error": True})

        return Response(response_data, status=status.HTTP_200_OK)
