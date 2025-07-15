#!/bin/bash

if [[ "$1" == "serve" ]]; then
    echo "Starting Uvicorn server..."
    exec uvicorn inference:app --host 0.0.0.0 --port 8080
else
    # Execute the command passed to the container
    exec "$@"
fi
