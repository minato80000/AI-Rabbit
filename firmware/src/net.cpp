#include "net.h"

#include <ArduinoJson.h>
#include <WebSocketsClient.h>
#include <WiFi.h>
#include <string.h>  // strcmp, strlen, memcpy

#include "audio_out.h"
#include "config.h"
#include "face.h"

Net net;

namespace {
WebSocketsClient ws;
}

void Net::begin() {
  connectWifi();

  ws.begin(PC_HOST, PC_PORT, WS_PATH);
  ws.onEvent([](WStype_t type, uint8_t* payload, size_t length) {
    net.onEvent((int)type, payload, length);
  });
  ws.setReconnectInterval(WS_RECONNECT_MS);
  // 無通信でも接続が生きているか確かめる
  ws.enableHeartbeat(15000, 3000, 2);

  Serial.printf("[net] 接続先 ws://%s:%d%s\n", PC_HOST, (int)PC_PORT, WS_PATH);
}

void Net::connectWifi() {
  if (strlen(WIFI_SSID) == 0) {
    Serial.println("[net] WiFi 未設定。secrets.local.h を作ってください");
    return;
  }
  Serial.printf("[net] WiFi 接続中: %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
    delay(250);
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("[net] WiFi 接続 %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("[net] WiFi 接続できず。あとで再試行します");
  }
}

void Net::update() {
  ws.loop();

  // WiFi が切れたら繋ぎ直す
  if (WiFi.status() != WL_CONNECTED && millis() - last_attempt_ms_ > 10000) {
    last_attempt_ms_ = millis();
    connectWifi();
  }

  // 鳴らし終わったら知らせる
  if (audio_done_pending_ && audio_out.finished()) {
    audio_done_pending_ = false;
    sendAudioDone();
  }
}

void Net::onEvent(int type, uint8_t* payload, size_t length) {
  switch ((WStype_t)type) {
    case WStype_CONNECTED: {
      connected_ = true;
      face.setConnected(true);
      Serial.println("[net] PC に接続しました");
      JsonDocument doc;
      doc["t"] = "hello";
      doc["fw"] = FW_VERSION;
      char out[128];
      serializeJson(doc, out, sizeof(out));
      ws.sendTXT(out);
      break;
    }
    case WStype_DISCONNECTED:
      connected_ = false;
      face.setConnected(false);
      audio_out.flush();
      Serial.println("[net] PC から切断されました");
      break;

    case WStype_TEXT:
      // payload は NUL 終端されていないことがある
      if (length < 512) {
        char buf[512];
        memcpy(buf, payload, length);
        buf[length] = '\0';
        handleText(buf);
      }
      break;

    case WStype_BIN:
      // PCM (s16le)。バイト列をそのままサンプル列として扱う
      audio_out.push(reinterpret_cast<const int16_t*>(payload), length / 2);
      break;

    default:
      break;
  }
}

void Net::handleText(const char* text) {
  JsonDocument doc;
  if (deserializeJson(doc, text) != DeserializationError::Ok) {
    Serial.printf("[net] JSON として読めません: %s\n", text);
    return;
  }
  const char* t = doc["t"] | "";

  if (strcmp(t, "state") == 0) {
    face.set(parseState(doc["v"] | "idle"), parseEmotion(doc["emotion"] | "neutral"));

  } else if (strcmp(t, "audio_begin") == 0) {
    uint32_t rate = doc["rate"] | AUDIO_SAMPLE_RATE;
    audio_out.beginStream(rate);
    audio_done_pending_ = true;

  } else if (strcmp(t, "audio_end") == 0) {
    audio_out.endStream();

  } else if (strcmp(t, "audio_flush") == 0) {
    audio_out.flush();
    audio_done_pending_ = false;

  } else {
    Serial.printf("[net] 未知のメッセージ: %s\n", t);
  }
}

void Net::sendJson(const char* json) {
  if (connected_) ws.sendTXT(json);
}

void Net::sendTouch(int x, int y) {
  JsonDocument doc;
  doc["t"] = "touch";
  doc["x"] = x;
  doc["y"] = y;
  char out[96];
  serializeJson(doc, out, sizeof(out));
  sendJson(out);
}

void Net::sendImu(const char* event) {
  JsonDocument doc;
  doc["t"] = "imu";
  doc["event"] = event;
  char out[96];
  serializeJson(doc, out, sizeof(out));
  sendJson(out);
}

void Net::sendAudioDone() {
  sendJson("{\"t\":\"audio_done\"}");
}
