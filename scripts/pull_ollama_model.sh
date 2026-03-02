#!/bin/sh
# Pull the default Ollama model after the container starts.
# Run once after `docker compose up`:
#   docker compose exec ollama sh /scripts/pull_ollama_model.sh
#
# Or as a one-liner:
#   docker compose exec ollama ollama pull llama3.2

set -e

MODEL=${OLLAMA_MODEL:-llama3.2}

echo "Pulling Ollama model: $MODEL"
ollama pull "$MODEL"
echo "Done. Model $MODEL is ready."

# Optional: also pull a smaller model for quick analysis
# ollama pull phi3:mini
