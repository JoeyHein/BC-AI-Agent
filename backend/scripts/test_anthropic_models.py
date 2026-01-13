"""
Test which Anthropic models are accessible with our API key
"""
import sys
from pathlib import Path

# Add parent directory to path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv()

from app.config import settings
from anthropic import Anthropic
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_model(client, model_name):
    """Test if a model is accessible"""
    try:
        logger.info(f"Testing model: {model_name}")
        response = client.messages.create(
            model=model_name,
            max_tokens=10,
            messages=[{"role": "user", "content": "Say 'test'"}]
        )
        logger.info(f"  ✓ SUCCESS - {model_name} is accessible")
        logger.info(f"  Response: {response.content[0].text}")
        return True
    except Exception as e:
        logger.error(f"  ✗ FAILED - {model_name}: {str(e)}")
        return False

def main():
    """Test various Anthropic models"""
    logger.info("="*80)
    logger.info("TESTING ANTHROPIC API KEY AND MODELS")
    logger.info("="*80)

    if not settings.ANTHROPIC_API_KEY:
        logger.error("No Anthropic API key configured!")
        return

    logger.info(f"\nAPI Key: {settings.ANTHROPIC_API_KEY[:20]}...")

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    # Test various model names
    models_to_test = [
        # Claude 3.5 Sonnet variations
        "claude-3-5-sonnet-latest",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-sonnet-20240620",

        # Claude 3 Opus
        "claude-3-opus-latest",
        "claude-3-opus-20240229",

        # Claude 3 Sonnet (older)
        "claude-3-sonnet-20240229",

        # Claude 3 Haiku
        "claude-3-haiku-20240307",

        # Try newer models if available
        "claude-sonnet-4-5-20250929",
    ]

    logger.info("\nTesting models...")
    logger.info("="*80)

    successful_models = []
    for model in models_to_test:
        if test_model(client, model):
            successful_models.append(model)
        logger.info("")

    logger.info("="*80)
    logger.info("SUMMARY")
    logger.info("="*80)
    logger.info(f"Tested {len(models_to_test)} models")
    logger.info(f"Successful: {len(successful_models)}")
    logger.info(f"Failed: {len(models_to_test) - len(successful_models)}")

    if successful_models:
        logger.info("\nWorking models:")
        for model in successful_models:
            logger.info(f"  ✓ {model}")
    else:
        logger.error("\n⚠️  NO MODELS WORKING! Check API key permissions.")

if __name__ == "__main__":
    main()
