SetupInstructions
============

# Farmer.chat setup guide

## Overview
Farmer.chat is a project written in python, enabled with Django-Rest framework to expose the functionality via APIs for multiple interfaces. Peewee ORM framework is used to interact with the database.

## Requirements
1. Linux or Mac OS
2. Python 3.9 or 3.10
3. VScode or other supporting IDE
4. PostgreSQL database (V 15.x)
5. Google application credentials JSON file for translation services
6. Open AI account with api key

**Note**:  Sl No. 4, 5 and 6 will be setup for the hackathon day.

# Steps

1. Clone the [repo](https://github.com/digitalgreenorg/agri.chat/tree/opensource-project) into an empty directory in IDE
2. Place the .env and .config.env file directly in the project root directory (templates will be attached)
3. Enter correct values in .env file for database, Google application credentials and open AI API key
4. Ensure the Farmstack base URL is configured in .config.env file
5. Open a terminal and Set current directory to the project root directory.
6. Run the below commands in sequence      
        - *python3 -m venv myenv* to create a virtual environment.
        - *source myenv/bin/activate* to activate the virtual environment
        - *pip install -r requirements.txt* to install the dependencies.
        - *python3 manage.py runserver* to start the development server. The APIs are accessible at http://localhost:8000/api/chat/

** Note: ** correct env files will be shared for hackathon

## Database setup steps (will be pre setup for hackathon)

1. Set current directory to project root directory after configuring env files
2. Run command * cd database *
3. Run command * pem migrate*

## API specification

Link to the postman collection will be provided here.