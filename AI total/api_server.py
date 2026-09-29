"""REST-only entrypoint. Configure TRAINING_API_TOKEN before starting."""
import sys
from web_ui import main

if __name__ == '__main__':
    sys.argv.extend(['--api-only', '--no-browser', '--no-legacy-api'])
    main()
