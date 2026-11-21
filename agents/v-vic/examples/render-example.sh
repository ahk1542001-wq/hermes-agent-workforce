#!/bin/sh
# Synthetic offline example: two generated plates and a single continuous tone.
set -eu

if [ "$#" -ne 1 ]; then
    echo "Usage: sh render-example.sh NEW_OUTPUT_DIRECTORY" >&2
    exit 2
fi

mkdir -- "$1"
cd -- "$1"

ffmpeg -nostdin -v error -f lavfi -i 'color=c=0x182127:s=360x640:r=24:d=1' \
    -an -c:v libx264 -pix_fmt yuv420p 01-intro.mp4
ffmpeg -nostdin -v error -f lavfi -i 'color=c=0x46796e:s=360x640:r=24:d=1' \
    -an -c:v libx264 -pix_fmt yuv420p 02-detail.mp4

printf "file '01-intro.mp4'\nfile '02-detail.mp4'\n" > edit-list.txt
ffmpeg -nostdin -v error -f concat -safe 1 -i edit-list.txt \
    -f lavfi -i 'sine=frequency=440:sample_rate=48000:duration=2' \
    -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -movflags +faststart review.mp4

ffmpeg -nostdin -v error -xerror -i review.mp4 -map 0:v:0 -map 0:a:0 -f null -
frames=$(ffprobe -v error -select_streams v:0 -count_frames \
    -show_entries stream=nb_read_frames -of default=nw=1:nk=1 review.mp4)
test "$frames" = 48
echo 'Review export passed full decode and 48-frame check: review.mp4'
