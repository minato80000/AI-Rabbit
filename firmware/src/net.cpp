#include "net.h"

#include <ArduinoJson.h>
#include <WiFi.h>
#include <string.h>  // strcmp, strlen, memcpy, strncmp

#include "audio_out.h"
#include "config.h"
#include "face.h"
#include "mic_in.h"

// 待ち受ける側と繋ぎに行く側で必要なクラスが違う。両方積むとメモリが惜しいので
// 使うほうだけを取り込む
#if LINK_MODE == LINK_ROBOT_AP
  #include <WebSocketsServer.h>
#else
  #include <WebSocketsClient.h>
#endif

Net net;

namespace {

#if LINK_MODE == LINK_ROBOT_AP

WebSocketsServer wss(PC_PORT);
// 入れるのは PC 1台だけなので、宛先を選ばず全員に投げてよい
inline void linkSendTXT(const char* s) { wss.broadcastTXT(s); }
inline void linkSendBIN(const uint8_t* p, size_t n) { wss.broadcastBIN(p, n); }

#else

WebSocketsClient ws;
inline void linkSendTXT(const char* s) { ws.sendTXT(s); }
inline void linkSendBIN(const uint8_t* p, size_t n) { ws.sendBIN(p, n); }

#endif

}  // namespace

void Net::begin() {
#if LINK_MODE == LINK_ROBOT_AP
  startAp();

  wss.begin();
  wss.onEvent([](uint8_t num, WStype_t type, uint8_t* payload, size_t length) {
    net.onEvent((int)type, payload, length, num);
  });
  Serial.printf("[net] 待ち受け ws://%s:%d%s\n",
                WiFi.softAPIP().toString().c_str(), (int)PC_PORT, WS_PATH);
#else
  connectWifi();

  ws.begin(PC_HOST, PC_PORT, WS_PATH);
  ws.onEvent([](WStype_t type, uint8_t* payload, size_t length) {
    net.onEvent((int)type, payload, length);
  });
  ws.setReconnectInterval(WS_RECONNECT_MS);
  // 無通信でも接続が生きているか確かめる
  ws.enableHeartbeat(15000, 3000, 2);

  Serial.printf("[net] 接続先 ws://%s:%d%s\n", PC_HOST, (int)PC_PORT, WS_PATH);
#endif
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

void Net::startAp() {
  // パスワードは8文字以上ないと WPA2 にできない。短ければ暗号化なしで立てる。
  // 黙って開放するのは危ないので必ず知らせる
  const bool open_network = strlen(AP_PASSWORD) < 8;
  if (open_network) {
    Serial.println(
        "[net] AP_PASSWORD が8文字未満です。暗号化なしの AP になります "
        "(secrets.local.h で設定してください)");
  }

  WiFi.mode(WIFI_AP);
  const bool ok = WiFi.softAP(AP_SSID, open_network ? nullptr : AP_PASSWORD,
                              AP_CHANNEL, 0, AP_MAX_CLIENTS);
  if (!ok) {
    Serial.println("[net] AP を立てられませんでした");
    return;
  }
  Serial.printf("[net] AP \"%s\" ch%d %s / %s\n", AP_SSID, (int)AP_CHANNEL,
                open_network ? "暗号化なし" : "WPA2",
                WiFi.softAPIP().toString().c_str());
  Serial.println("[net] PC の WiFi をこの SSID に切り替えてください");
}

void Net::update() {
#if LINK_MODE == LINK_ROBOT_AP
  wss.loop();
#else
  ws.loop();

  // WiFi が切れたら繋ぎ直す
  if (WiFi.status() != WL_CONNECTED && millis() - last_attempt_ms_ > 10000) {
    last_attempt_ms_ = millis();
    connectWifi();
  }
#endif

  // 鳴らし終わったら知らせる
  if (audio_done_pending_ && audio_out.finished()) {
    audio_done_pending_ = false;
    sendAudioDone();
  }
}

void Net::onEvent(int type, uint8_t* payload, size_t length, uint8_t client) {
  (void)client;

  switch ((WStype_t)type) {
    case WStype_CONNECTED: {
#if LINK_MODE == LINK_ROBOT_AP
      // 待ち受ける側では payload に接続先のパスが入る。PC 側のサーバも
      // 同じ検査をしているので、向きが変わっても振る舞いを揃えておく
      if (payload != nullptr && length > 0 &&
          (length != strlen(WS_PATH) ||
           strncmp((const char*)payload, WS_PATH, length) != 0)) {
        Serial.printf("[net] 想定外のパスで接続: %.*s\n", (int)length,
                      (const char*)payload);
        wss.disconnect(client);
        break;
      }
#endif
      connected_ = true;
      face.setConnected(true);
      Serial.println("[net] PC に接続しました");
      JsonDocument doc;
      doc["t"] = "hello";
      doc["fw"] = FW_VERSION;
      doc["mic"] = true;  // マイク入力を持つ機体だと伝える
      char out[128];
      serializeJson(doc, out, sizeof(out));
      linkSendTXT(out);
      break;
    }
    case WStype_DISCONNECTED:
#if LINK_MODE == LINK_ROBOT_AP
      // 他にまだ繋がっているなら切断扱いにしない
      if (wss.connectedClients() > 0) break;
#endif
      connected_ = false;
      face.setConnected(false);
      audio_out.flush();
      mic_in.setWanted(false, 0);  // 送り先が居ないので録らない
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

  } else if (strcmp(t, "mic") == 0) {
    // PC がマイクを開かせにきた。実際に開くかは mic_in が決める
    // （鳴っているあいだは I2S を空けられない）
    mic_in.setWanted(doc["on"] | false, doc["rate"] | MIC_SAMPLE_RATE);

  } else {
    Serial.printf("[net] 未知のメッセージ: %s\n", t);
  }
}

void Net::sendJson(const char* json) {
  if (connected_) linkSendTXT(json);
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

void Net::sendMicFrame(const int16_t* data, size_t samples) {
  if (!connected_) return;
  // ESP32 はリトルエンディアンなので、そのまま s16le として読める
  linkSendBIN(reinterpret_cast<const uint8_t*>(data), samples * sizeof(int16_t));
}
