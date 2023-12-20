from pymongo import MongoClient
from flask import Flask
from flask_restful import Api, Resource
from flask_restful_swagger_3 import Api as SwaggerApi

app = Flask(__name__)
api = Api(app)
swagger_api = SwaggerApi(app)

# MongoDB connection details
mongo_uri = 'mongodb://localhost:27017/'
database_name = 'Jfrog-Nexus'
collection_name = 'jfrog'

# Connect to MongoDB
client = MongoClient(mongo_uri)
db = client[database_name]
collection = db[collection_name]

# Fetch data from MongoDB
methods_and_endpoints = [
    {"method": doc["method"], "endpoint": doc["endpoint"], "description": doc["description"]}
    for doc in collection.find()
]

# Function to create Swagger documentation dynamically
def create_swagger_for_methods(methods_and_endpoints):
    for data in methods_and_endpoints:
        class DynamicResource(Resource):
            def __init__(self, **kwargs):
                self.method = data["method"]
                self.endpoint = data["endpoint"]
                self.description = data["description"]
                super().__init__(**kwargs)

            def get(self):
                """
                Swagger for {endpoint} endpoint.
                ---
                tags:
                  - {endpoint}
                description: {description}
                """
                # Implement your logic for handling the endpoint
                pass

        endpoint_name = f'DynamicResource_{data["endpoint"].replace("/", "_").strip("{}")}'
        swagger_api.add_resource(DynamicResource, data["endpoint"], endpoint=endpoint_name)

if __name__ == '__main__':
    create_swagger_for_methods(methods_and_endpoints)
    app.run(debug=True)
