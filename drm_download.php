<?php

$config = [
    'mpd_url' => 'https://d13yevwzck7i9p.cloudfront.net/drm-aac/b8bac05c3300c41473e81d7a2f0800a4888da492/96a5a976681b4dbe95d31d09836beb6a/69d7967f7ced37836a15e8ad/h264.mpd',
    
    'keys' => [
        '4cf5bcad5ac259c9b8b559e1f089cd0f' => '01cf474ae87e04a452566c7a3868a051',
        'f404ef10e8ee54028daa3f853ce427f4' => 'c654673794a8efccae18da009f293869',
        'd018ae0e24ca5f5b91a2492cc98399d2' => '357b91af6b239cbea224650b5e727058',
        '31de92b37e3e5b899edc05f826dbe530' => '79a2ae9afdb44c60bd31bd8a6a5953eb',
    ],

    'quality' => '64k',
    'output_name' => 'testing_audio',
    'mp4decrypt_path' => __DIR__ . '\\Bento4-SDK-1-6-0-641.x86_64-microsoft-win32\\bin\\mp4decrypt.exe',
    'ffmpeg_path' => 'ffmpeg',
];

function logMsg($msg, $type = 'INFO') {
    $timestamp = date('H:i:s');
    $colors = [
        'INFO'    => "\033[36m",
        'SUCCESS' => "\033[32m",
        'ERROR'   => "\033[31m",
        'WARN'    => "\033[33m",
        'STEP'    => "\033[35m",
    ];
    $reset = "\033[0m";
    $color = $colors[$type] ?? "\033[0m";
    echo "{$color}[{$timestamp}] [{$type}] {$msg}{$reset}\n";
}

function checkTool($path, $name) {
    $cmd = PHP_OS_FAMILY === 'Windows' ? "where {$path} 2>NUL" : "which {$path} 2>/dev/null";
    exec($cmd, $output, $returnCode);
    
    if ($returnCode !== 0) {
        if (!file_exists($path)) {
            return false;
        }
    }
    return true;
}

function downloadFile($url, $outputPath) {
    logMsg("Downloading: " . basename($outputPath) . "...");
    logMsg("URL: {$url}", 'INFO');
    
    $ch = curl_init();
    $fp = fopen($outputPath, 'wb');
    
    if (!$fp) {
        logMsg("Cannot create file: {$outputPath}", 'ERROR');
        return false;
    }
    
    curl_setopt_array($ch, [
        CURLOPT_URL => $url,
        CURLOPT_FILE => $fp,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_MAXREDIRS => 5,
        CURLOPT_TIMEOUT => 300,
        CURLOPT_SSL_VERIFYPEER => false,
        CURLOPT_USERAGENT => 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        CURLOPT_NOPROGRESS => false,
        CURLOPT_PROGRESSFUNCTION => function($ch, $dlTotal, $dlNow, $ulTotal, $ulNow) {
            static $lastPercent = -1;
            if ($dlTotal > 0) {
                $percent = round(($dlNow / $dlTotal) * 100);
                if ($percent !== $lastPercent && $percent % 10 === 0) {
                    $lastPercent = $percent;
                    $sizeMB = round($dlNow / 1048576, 2);
                    $totalMB = round($dlTotal / 1048576, 2);
                    echo "\r  >> Progress: {$percent}% ({$sizeMB} MB / {$totalMB} MB)";
                }
            }
            return 0;
        },
    ]);
    
    $result = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $error = curl_error($ch);
    
    curl_close($ch);
    fclose($fp);
    
    echo "\n";
    
    if (!$result || $httpCode !== 200) {
        logMsg("Download failed! HTTP Code: {$httpCode}, Error: {$error}", 'ERROR');
        @unlink($outputPath);
        return false;
    }
    
    $size = filesize($outputPath);
    $sizeMB = round($size / 1048576, 2);
    logMsg("Downloaded: {$sizeMB} MB", 'SUCCESS');
    return true;
}

function parseMPD($mpdContent, $quality) {
    $xml = simplexml_load_string($mpdContent);
    if (!$xml) {
        logMsg("MPD parse failed!", 'ERROR');
        return null;
    }
    
    $xml->registerXPathNamespace('mpd', 'urn:mpeg:dash:schema:mpd:2011');
    $xml->registerXPathNamespace('cenc', 'urn:mpeg:cenc:2013');
    
    $targetFile = "protected_audio_mpd_{$quality}.mp4";
    
    $representations = $xml->xpath('//mpd:Representation');
    
    foreach ($representations as $rep) {
        $baseURL = (string) $rep->BaseURL;
        if ($baseURL === $targetFile) {
            $bandwidth = (string) $rep->attributes()->bandwidth;
            logMsg("Found quality: {$quality} (bandwidth: {$bandwidth} bps)");
            return [
                'file' => $baseURL,
                'bandwidth' => $bandwidth,
                'codec' => (string) $rep->attributes()->codecs,
            ];
        }
    }
    
    logMsg("Quality '{$quality}' not found in MPD!", 'ERROR');
    return null;
}

echo "\n";
echo "╔══════════════════════════════════════════════════════╗\n";
echo "║     Widevine DRM Audiobook Downloader (PHP)         ║\n";
echo "╠══════════════════════════════════════════════════════╣\n";
echo "║  Step 1: Check Tools                                ║\n";
echo "║  Step 2: Parse MPD                                  ║\n";
echo "║  Step 3: Download Encrypted Audio                   ║\n";
echo "║  Step 4: Decrypt with mp4decrypt                    ║\n";
echo "║  Step 5: Convert to MP3 (optional, needs ffmpeg)    ║\n";
echo "╚══════════════════════════════════════════════════════╝\n";
echo "\n";

logMsg("STEP 1: Checking required tools...", 'STEP');

$hasMp4decrypt = checkTool($config['mp4decrypt_path'], 'mp4decrypt');
$hasFfmpeg = checkTool($config['ffmpeg_path'], 'ffmpeg');

if (!$hasMp4decrypt) {
    logMsg("mp4decrypt.exe not found!", 'ERROR');
    logMsg("Download Bento4 from: https://www.bento4.com/downloads/", 'WARN');
    logMsg("Expected path: " . $config['mp4decrypt_path'], 'WARN');
    exit(1);
}
logMsg("mp4decrypt found!", 'SUCCESS');

if (!$hasFfmpeg) {
    logMsg("ffmpeg not found — MP3 conversion will be skipped", 'WARN');
} else {
    logMsg("ffmpeg found!", 'SUCCESS');
}

logMsg("STEP 2: Parsing MPD manifest...", 'STEP');

$mpdContent = file_get_contents($config['mpd_url'], false, stream_context_create([
    'http' => [
        'header' => "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)\r\n",
    ],
    'ssl' => [
        'verify_peer' => false,
        'verify_peer_name' => false,
    ],
]));

if (!$mpdContent) {
    logMsg("Failed to fetch MPD!", 'ERROR');
    exit(1);
}

$audioInfo = parseMPD($mpdContent, $config['quality']);
if (!$audioInfo) {
    exit(1);
}

$mpdBaseUrl = dirname($config['mpd_url']);
$audioUrl = $mpdBaseUrl . '/' . $audioInfo['file'];
logMsg("Audio URL: {$audioUrl}");

logMsg("STEP 3: Downloading encrypted audio file...", 'STEP');

$encryptedFile = __DIR__ . DIRECTORY_SEPARATOR . 'encrypted_audio.mp4';
$decryptedFile = __DIR__ . DIRECTORY_SEPARATOR . $config['output_name'] . '.m4a';
$mp3File = __DIR__ . DIRECTORY_SEPARATOR . $config['output_name'] . '.mp3';

if (!downloadFile($audioUrl, $encryptedFile)) {
    logMsg("Download failed! Check your internet connection.", 'ERROR');
    exit(1);
}

logMsg("STEP 4: Decrypting audio with mp4decrypt...", 'STEP');

$keyArgs = '';
foreach ($config['keys'] as $kid => $key) {
    $keyArgs .= " --key {$kid}:{$key}";
}

$mp4decryptPath = $config['mp4decrypt_path'];
if (strpos($mp4decryptPath, DIRECTORY_SEPARATOR) === false && strpos($mp4decryptPath, '/') === false) {
    $localPath = __DIR__ . DIRECTORY_SEPARATOR . $mp4decryptPath;
    if (file_exists($localPath)) {
        $mp4decryptPath = $localPath;
    }
}

$decryptCmd = "\"{$mp4decryptPath}\"{$keyArgs} \"{$encryptedFile}\" \"{$decryptedFile}\"";
logMsg("Running: mp4decrypt with " . count($config['keys']) . " keys...");

exec($decryptCmd . ' 2>&1', $decryptOutput, $decryptReturn);

if ($decryptReturn !== 0) {
    logMsg("Decryption failed!", 'ERROR');
    logMsg("Command output: " . implode("\n", $decryptOutput), 'ERROR');
    logMsg("Full command: {$decryptCmd}", 'ERROR');
    exit(1);
}

logMsg("Decryption successful!", 'SUCCESS');

@unlink($encryptedFile);
logMsg("Cleaned up encrypted file.", 'INFO');

if ($hasFfmpeg) {
    logMsg("STEP 5: Converting to MP3 with ffmpeg...", 'STEP');
    
    $ffmpegCmd = "\"{$config['ffmpeg_path']}\" -i \"{$decryptedFile}\" -codec:a libmp3lame -q:a 2 -y \"{$mp3File}\" 2>&1";
    logMsg("Running ffmpeg conversion...");
    
    exec($ffmpegCmd, $ffmpegOutput, $ffmpegReturn);
    
    if ($ffmpegReturn !== 0) {
        logMsg("MP3 conversion failed, but M4A file is ready!", 'WARN');
        logMsg("FFmpeg output: " . implode("\n", $ffmpegOutput), 'WARN');
    } else {
        $mp3Size = round(filesize($mp3File) / 1048576, 2);
        logMsg("MP3 conversion complete! Size: {$mp3Size} MB", 'SUCCESS');
        logMsg("Both M4A and MP3 files are available.", 'INFO');
    }
} else {
    logMsg("STEP 5: Skipped (ffmpeg not found). M4A file is ready.", 'WARN');
}

echo "\n";
echo "╔══════════════════════════════════════════════════════╗\n";
echo "║                    COMPLETE!                        ║\n";
echo "╠══════════════════════════════════════════════════════╣\n";

if (file_exists($decryptedFile)) {
    $m4aSize = round(filesize($decryptedFile) / 1048576, 2);
    echo "║  M4A: {$config['output_name']}.m4a ({$m4aSize} MB)" . str_repeat(' ', max(0, 20 - strlen($m4aSize))) . "║\n";
}
if (file_exists($mp3File)) {
    $mp3Size = round(filesize($mp3File) / 1048576, 2);
    echo "║  MP3: {$config['output_name']}.mp3 ({$mp3Size} MB)" . str_repeat(' ', max(0, 20 - strlen($mp3Size))) . "║\n";
}

echo "║  Location: " . __DIR__ . str_repeat(' ', max(0, 10)) . "\n";
echo "╚══════════════════════════════════════════════════════╝\n";
echo "\n";
