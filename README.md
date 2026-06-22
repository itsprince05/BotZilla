# PocketFM Downloader Telegram Bot

Telegram bot to download PocketFM episodes with selectable quality, automatic decryption and MP3 upload.

## Features

PocketFM API integration  
Widevine DRM key extraction  
Episode range selection  
Quality selection (64 / 96 / 128 / 192 kbps)  
MP3 output  
Episode sequence naming  
Batch upload  
Cancel running download  
Group and private chat support  
Docker deployment support  

## Commands

/start  
Start the bot

/help  
Show help guide

/info  
Show user or group information

/stats  
Show bot statistics

/cancel  
Cancel running download

/ld <show_link>  
Load PocketFM show

Example

/ld https://pocketfm.com/show/abcd

## Download Flow

1. Send show link

/ld show_link

2. Select audio quality

3. Send episode range

Examples

1-10  
1,2,4  
1-5,10,20  

Bot will download, decrypt and upload episodes.

## Output Naming

Episodes are uploaded as

Epi.100 - Episode Title.mp3  
Epi.101 - Episode Title.mp3  

## Project Structure

pocketfm_bot/

bot.py  
config.py  
helpers.py  
database.py  
pfm_downloader.py  

requirements.txt  
Dockerfile  
docker-compose.yml  
.dockerignore  

l3.wvd
   l3.wvd  

downloads/  
logs/  
temp/  

## Requirements

Python 3.10+

Install dependencies

pip install -r requirements.txt

## Environment Configuration

Edit config.py or use environment variables.

Required values

API_ID  
API_HASH  
BOT_TOKEN  

## Run Bot

python bot.py

## Docker Deployment

Build image

docker build -t pocketfm-bot .

Run container

docker run -d --name pocketfm --restart always pocketfm-bot

Check logs

docker logs -f pocketfm

## Supported Features

Quality selection  
Episode range parser  
Widevine decryption  
MP3 conversion  
Batch uploads  
Cancel command  
Group usage  

## Notes

The bot downloads PocketFM streams and converts them to MP3 format.

Widevine device file required

devices/l3.wvd

## License
MIT
LICENSE 
This project is for educational use only.
