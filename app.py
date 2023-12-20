from flask import Flask,jsonify
from flask_restplus import Api, Resource, reqparse
import requests
import os
import re
import shutil

app = Flask(__name__)
api = Api(app, version='1.0', title='Artifactory API',
          description='API for migrating artifacts from Nexus to Artifactory')

# Class for Artifact Migration Operations
ns_artifact = api.namespace('Nexus ', description='Artifact migration operations')

get_parser = reqparse.RequestParser()
get_parser.add_argument('NEXUS_URL', type=str, required=True)
get_parser.add_argument('NEXUS_USERNAME', type=str, required=True)
get_parser.add_argument('NEXUS_PASSWORD', type=str, required=True)

@ns_artifact.route('/nexus-repositories')
class NexusRepositories(Resource):
    """
    Resource for retrieving information about Nexus repositories.
    """

    @api.expect(get_parser)
    def get(self):
        """
        GET method for retrieving information about Nexus repositories.
        """
        args = get_parser.parse_args()
        nexus_url = args['NEXUS_URL']
        username = args['NEXUS_USERNAME']
        password = args['NEXUS_PASSWORD']
        repositories_url = f"{nexus_url}/service/rest/v1/repositories"

        try:
            response = requests.get(repositories_url, auth=(username, password))

            if response.status_code == 200:
                repositories = response.json()
                return repositories, 200
            else:
                return {'error': f"Error: {response.status_code}. {response.text}"}, response.status_code

        except requests.RequestException as e:
            # Log the error for debugging purposes
            print(f"Error during request: {e}")
            return {'error': f"Error during request: {e}"}, 500
# Parser for artifact migration operations
parser = reqparse.RequestParser()
parser.add_argument('NEXUS_URL', type=str, required=True)
parser.add_argument('NEXUS_USERNAME', type=str, required=True)
parser.add_argument('NEXUS_PASSWORD', type=str, required=True)
parser.add_argument('JFROG_URL', type=str, required=True)
parser.add_argument('JFROG_API_KEY', type=str, required=True)
parser.add_argument('REPO_NAME', type=str, required=False)  # Optional repository name

@ns_artifact.route('/push-repos')
class PushRepositories(Resource):
    """
    Resource for pushing artifacts from Nexus repositories to JFrog Artifactory.
    """

    @api.expect(parser)
    def post(self):
        """
        POST method for pushing artifacts from Nexus repositories to JFrog Artifactory.
        """
        args = parser.parse_args()
        nexus_url = args['NEXUS_URL']
        username = args['NEXUS_USERNAME']
        password = args['NEXUS_PASSWORD']
        jfrog_url = args['JFROG_URL']
        jfrog_api_key = args['JFROG_API_KEY']
        repo_name = args.get('REPO_NAME', None)

        results = []
        created_repositories = []

        # Fetch all repositories from Nexus
        repositories = get_all_repositories(nexus_url, username, password)

        for repo in repositories:
            repository_name = repo['name']

            # Skip repositories if REPO_NAME is provided and does not match the current repository
            if repo_name and repo_name != repository_name:
                continue

            # Create repository in JFrog Artifactory
            create_jfrog_repository(jfrog_url, jfrog_api_key, repo, created_repositories)

            # Fetch artifacts in the repository
            artifacts = get_artifacts_in_repository(nexus_url, username, password, repository_name)

            for artifact in artifacts:
                artifact_path = artifact.get('path', '')
                artifact_filename = artifact.get('name', '')

                result = download_and_push_artifact(
                    nexus_url, username, password, jfrog_url, jfrog_api_key,
                    repository_name, artifact_path, artifact_filename
                )
                results.append(result)

        # Clean up local directories after pushing files to JFrog
        cleanup_local_directories()

        response_data = {
            'message': 'Migration completed successfully',
            'created_repositories': created_repositories,
            'migrated_artifacts': [
                {
                    'repository_name': result['repository_name'],
                    'artifact_path': result['artifact_path'],
                    'artifact_filename': result['artifact_filename'],
                }
                for result in results
            ]
        }

        return jsonify(response_data)

def download_and_push_artifact(nexus_url, nexus_username, nexus_password, jfrog_url, jfrog_api_key,
                               repository_name, artifact_path, artifact_filename):
    result = download_artifact(nexus_url, nexus_username, nexus_password, repository_name,
                               artifact_path, artifact_filename)

    if 'error' not in result:
        # Push the downloaded artifact to JFrog Artifactory
        push_artifact_to_artifactory(
            jfrog_url, jfrog_api_key, result['local_file_path'],
            repository_name, artifact_path, artifact_filename
        )

    return result

def create_jfrog_repository(jfrog_url, jfrog_api_key, nexus_repo, created_repositories):
    repository_name = nexus_repo['name']
    nexus_repo_type = nexus_repo['type'].lower()

    if nexus_repo_type == 'hosted':
        rclass_value = 'local'
    elif nexus_repo_type == 'group':
        rclass_value = 'virtual'
    elif nexus_repo_type == 'proxy':
        rclass_value = 'remote'
    else:
        rclass_value = 'federated'

    create_repo_data = {
        "key": repository_name,
        "rclass": rclass_value,
        "packageType": nexus_repo['format'],
        "url": f'{jfrog_url}/artifactory/api/repositories/{repository_name}'
    }

    create_repo_response = requests.put(
        f'{jfrog_url}/artifactory/api/repositories/{repository_name}',
        headers={'Content-Type': 'application/json', 'X-JFrog-Art-Api': jfrog_api_key},
        json=create_repo_data
    )

    if create_repo_response.status_code == 200:
        created_repositories.append({'repository_name': repository_name})
        print(f"Repository '{repository_name}' created successfully in JFrog Artifactory.")
    elif create_repo_response.status_code == 400:
        print(f"Repository '{repository_name}' already exists in JFrog Artifactory.")
    else:
        print(f"Error creating repository '{repository_name}' in JFrog Artifactory: "
              f"{create_repo_response.status_code}, {create_repo_response.text}")

def cleanup_local_directories():
    current_directory = os.getcwd()
    for item in os.listdir(current_directory):
        item_path = os.path.join(current_directory, item)
        if os.path.isdir(item_path):
            shutil.rmtree(item_path)

def download_artifact(nexus_url, username, password, repository_name, artifact_path, artifact_filename):
    artifact_url = f"{nexus_url}/repository/{repository_name}/{artifact_path}/{artifact_filename}"

    try:
        response = requests.get(artifact_url, auth=(username, password))

        if response.status_code == 200:
            sanitized_filename = sanitize_filename(artifact_filename)
            local_file_path = os.path.join(os.getcwd(), f"{repository_name}_{artifact_path}_{sanitized_filename}")
            os.makedirs(os.path.dirname(local_file_path), exist_ok=True)

            with open(local_file_path, 'wb') as local_file:
                local_file.write(response.content)

            return {
                'repository_name': repository_name,
                'artifact_path': artifact_path,
                'artifact_filename': artifact_filename,
                'local_file_path': local_file_path,
            }

        else:
            return {'error': f"Failed to download artifact: {artifact_url}. Status Code: {response.status_code}"}

    except requests.RequestException as e:
        return {'error': f"Error during request: {e}"}

def push_artifact_to_artifactory(jfrog_url, jfrog_api_key, local_file_path, repository_name, artifact_path, artifact_filename):
    artifact_url = f"{jfrog_url}/artifactory/{repository_name}/{artifact_path}/{artifact_filename}"

    try:
        with open(local_file_path, 'rb') as local_file:
            response = requests.put(
                artifact_url,
                headers={'Content-Type': 'application/octet-stream', 'X-JFrog-Art-Api': jfrog_api_key},
                data=local_file.read(),
            )

        if response.status_code == 201:
            print(f"Artifact '{artifact_filename}' pushed successfully to repository '{repository_name}' in JFrog Artifactory.")
        else:
            print(f"Error pushing artifact '{artifact_filename}' to repository '{repository_name}' in JFrog Artifactory: "
                  f"{response.status_code}, {response.text}")

    except requests.RequestException as e:
        print(f"Error during request: {e}")

def get_all_repositories(nexus_url, username, password):
    repositories_url = f"{nexus_url}/service/rest/v1/repositories"

    try:
        response = requests.get(repositories_url, auth=(username, password))

        if response.status_code == 200:
            return response.json()
        else:
            return []

    except requests.RequestException as e:
        return [{'error': f"Error during request: {e}"}]

def get_artifacts_in_repository(nexus_url, username, password, repository_name):
    artifacts_url = f"{nexus_url}/service/rest/v1/search/assets?repository={repository_name}"

    try:
        response = requests.get(artifacts_url, auth=(username, password))

        if response.status_code == 200:
            artifacts = response.json().get('items', [])
            return artifacts

        else:
            return []

    except requests.RequestException as e:
        return [{'error': f"Error during request: {e}"}]

def sanitize_filename(filename):
    return re.sub(r'[\/:*?"<>|]', '_', filename)


ns_jfrog = api.namespace('jfrog', description='JFrog Repository Operations')

# Parser for deleting JFrog repositories
parser_delete = reqparse.RequestParser()
parser_delete.add_argument('key', type=str, help='Key of the repository', required=True)
parser_delete.add_argument('url', type=str, help='JFrog URL', required=True)
parser_delete.add_argument('api_token', type=str, help='JFrog API Token', required=True)

@ns_jfrog.route('/repository')
class JFrogRepositoryResource(Resource):
    """
    Resource for JFrog repository operations.
    """

    @ns_jfrog.expect(parser_delete)
    def delete(self):
        """
        DELETE method for deleting a JFrog repository.
        """
        args = parser_delete.parse_args(strict=True)

        jfrog_url = args['url']
        repository_key = args['key']
        complete_jfrog_url = f'{jfrog_url}/artifactory/api/repositories/{repository_key}'

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {args["api_token"]}'
        }

        response = requests.delete(complete_jfrog_url, headers=headers)

        return {
            "status_code": response.status_code,
            "response_text": response.text,
            "parsed_arguments": args
        }

# Additional classes for updating and retrieving JFrog repositories
parser_update = reqparse.RequestParser()
parser_update.add_argument('key', type=str, help='Key of the repository', required=True)
parser_update.add_argument('url', type=str, help='JFrog URL', required=True)
parser_update.add_argument('rclass', type=str, help='Repository class', required=True)
parser_update.add_argument('packageType', type=str, help='Package type', required=True)
parser_update.add_argument('description', type=str, help='Repository description', required=True)
parser_update.add_argument('api_token', type=str, help='JFrog API Token', required=True)

@ns_jfrog.route('/repository/update')
class JFrogRepositoryUpdateResource(Resource):
    """
    Resource for creating the  JFrog repository .
    """
    @ns_jfrog.expect(parser_update)
    def put(self):
        """
        PUT method for creating the JFrog repository .
        """
        args = parser_update.parse_args(strict=True)  

        jfrog_url = args['url']
        repository_key = args['key']
        complete_jfrog_url = f'{jfrog_url}/artifactory/api/repositories/{repository_key}'

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {args["api_token"]}'
        }

        data = {
            "key": args['key'],
            "rclass": args['rclass'],
            "url": args['url'],
            "packageType": args['packageType'],
            "description": args['description'],
        }

        response = requests.put(complete_jfrog_url, headers=headers, json=data)

        return {
            "status_code": response.status_code,
            "response_text": response.text,
            "parsed_arguments": args  
        }

# Class for retrieving information about JFrog repositories
parser_retrieve = reqparse.RequestParser()
parser_retrieve.add_argument('url', type=str, help='JFrog URL', required=True)
parser_retrieve.add_argument('api_token', type=str, help='JFrog API Token', required=True)

@ns_jfrog.route('/repositories')
class JFrogRepositoriesResource(Resource):
    """
    Resource for retrieving information about JFrog repositories.
    """
    @ns_jfrog.expect(parser_retrieve)
    def get(self):
        """
        GET method for retrieving information about JFrog repositories.
        """
        args = parser_retrieve.parse_args(strict=True)  # strict=True to abort on bad requests

        url = f'{args["url"]}/artifactory/api/repositories'
        
        headers = {
            'Authorization': f'Bearer {args["api_token"]}'
        }

        # Make the GET request
        response = requests.get(url, headers=headers, verify=False)

        return {
            "status_code": response.status_code,
            "response_content": response.json(),  
        }

# Class for retrieving information about a specific JFrog repository
@ns_jfrog.route('/repositories/<string:repositoryKey>')
class RepositoryDetailsResource(Resource):
    """
    Resource for retrieving information about a specific JFrog repository.
    """

    @ns_jfrog.expect(parser_retrieve)
    def get(self, repositoryKey):
        """
        GET method for retrieving information about a specific JFrog repository.
        """
        args = parser_retrieve.parse_args(strict=True)  # strict=True to abort on bad requests

        url = f'{args["url"]}/artifactory/api/repositories/{repositoryKey}'

        headers = {
            'Authorization': f'Bearer {args["api_token"]}'
        }

        # Make the GET request
        response = requests.get(url, headers=headers, verify=False)

        return {
            "status_code": response.status_code,
            "response_content": response.json(),
        }


if __name__ == '__main__':
    app.run(debug=True,port=5050,host="0.0.0.0")

