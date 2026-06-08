<?php

$config = [
    'mpd_url' => 'https://d13yevwzck7i9p.cloudfront.net/drm-aac/f629196ee7df34287ef2672e91fda9f939e9d02d/c8f6445a1e144c2b977e03745f405782/h264.mpd',
    
    'keys' => [
        '2e113798bafc5baaa51649eeddb54d85' => '4a9079301501fef93b6408794c4d32e7',
        '6dd219aa4b24518baf1e69ff57527596' => 'cd55841650f9da045f02768e23762237',
        'c88f169084455d9ba6b95af12e931e2d' => '5c58f1727dbe56703b9bf67119bdd7e2',
        'a76cd339dfea5fc58eae5bec4c52f2a2' => 'fd73eb0d2e90a2a697a3c928403d2dd7',
    ],

    'quality' => '64k',
    'output_name' => 'testing_audio',
    'mp4decrypt_path' => 'mp4decrypt',
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
echo "╚══════════════════════════════════════════════════════╝\n";
echo "\n";

logMsg("STEP 1: Checking required tools...", 'STEP');

$hasMp4decrypt = checkTool($config['mp4decrypt_path'], 'mp4decrypt');


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



echo "\n";
echo "╔══════════════════════════════════════════════════════╗\n";
echo "║                    COMPLETE!                        ║\n";
echo "╠══════════════════════════════════════════════════════╣\n";

if (file_exists($decryptedFile)) {
    $m4aSize = round(filesize($decryptedFile) / 1048576, 2);
    echo "║  M4A: {$config['output_name']}.m4a ({$m4aSize} MB)" . str_repeat(' ', max(0, 20 - strlen($m4aSize))) . "║\n";
}

echo "║  Location: " . __DIR__ . str_repeat(' ', max(0, 10)) . "\n";
echo "╚══════════════════════════════════════════════════════╝\n";
echo "\n";
