cd /Users/reixu/Documents/Projects/Anki-URL-Scheme

rsync -a \
  --exclude __pycache__ \
  --exclude config.json \
  --exclude user_files/ \
  src/ "$HOME/Library/Application Support/Anki2/addons21/anki_links/"
