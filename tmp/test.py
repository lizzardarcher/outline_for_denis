from textblob import TextBlob
from deep_translator import GoogleTranslator


def analyze_sentiment_ru(text):
    try:
        translator = GoogleTranslator(source='ru', target='en')
        translated = translator.translate(text)
        analysis = TextBlob(translated)
        polarity = analysis.sentiment.polarity

        if polarity > 0.3:
            return "positive"
        elif polarity < -0.3:
            return "negative"
        else:
            return "neutral"
    except Exception as e:
        print(f"Ошибка перевода или анализа: {e}")
        return "unknown"


text = "Хороший сервис. меня устраивает полностью."
sentiment = analyze_sentiment_ru(text)
print(f"Текст: {text}")
print(f"Тональность: {sentiment}")

text = "Плохой сервис. Никому не советую."
sentiment = analyze_sentiment_ru(text)
print(f"Текст: {text}")
print(f"Тональность: {sentiment}")

text = "средненький такой, ничего особенного."
sentiment = analyze_sentiment_ru(text)
print(f"Текст: {text}")
print(f"Тональность: {sentiment}")

'''
ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpmaERZUlJlSmE2R3pGZ3BCTmF0YXZ3@94.131.113.67:1080#%D0%A0%D0%BE%D1%81%D1%81%D0%B8%D1%8F%20%F0%9F%87%B7%F0%9F%87%BA%20pq.hosting%20RU-1%20%285566146968%29%20%5BShadowsocks%20-%20tcp%5D

ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpmaERZUlJlSmE2R3pGZ3BCTmF0YXZ3@94.131.121.53:1080#%D0%A0%D0%BE%D1%81%D1%81%D0%B8%D1%8F%20%F0%9F%87%B7%F0%9F%87%BA%20pq.hosting%20RU-2%20%285566146968%29%20%5BShadowsocks%20-%20tcp%5D

ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpmaERZUlJlSmE2R3pGZ3BCTmF0YXZ3@91.200.151.152:1080#%D0%9A%D0%B0%D0%B7%D0%B0%D1%85%D1%81%D1%82%D0%B0%D0%BD%20%F0%9F%87%B0%F0%9F%87%BF%20timeweb-cloud%20KZ6%20%285566146968%29%20%5BShadowsocks%20-%20tcp%5D

ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpmaERZUlJlSmE2R3pGZ3BCTmF0YXZ3@38.180.104.128:1080#%D0%A2%D1%83%D1%80%D1%86%D0%B8%D1%8F%20%F0%9F%87%B9%F0%9F%87%B7%20IS%20hosting%20TR2%20%285566146968%29%20%5BShadowsocks%20-%20tcp%5D

ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpmaERZUlJlSmE2R3pGZ3BCTmF0YXZ3@38.180.206.91:1080#%D0%9A%D0%B0%D0%B7%D0%B0%D1%85%D1%81%D1%82%D0%B0%D0%BD%20%F0%9F%87%B0%F0%9F%87%BF%20IS%20hosting%20KZ7%20%285566146968%29%20%5BShadowsocks%20-%20tcp%5D

ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpmaERZUlJlSmE2R3pGZ3BCTmF0YXZ3@38.180.185.71:1080#%D0%90%D1%80%D0%B3%D0%B5%D0%BD%D1%82%D0%B8%D0%BD%D0%B0%20%F0%9F%87%A6%F0%9F%87%B7%20IS%20hosting%20AG2%20%285566146968%29%20%5BShadowsocks%20-%20tcp%5D

ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpmaERZUlJlSmE2R3pGZ3BCTmF0YXZ3@45.15.156.52:1080#%D0%93%D0%B5%D1%80%D0%BC%D0%B0%D0%BD%D0%B8%D1%8F%20%F0%9F%87%A9%F0%9F%87%AA%20DE1%20

ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpmaERZUlJlSmE2R3pGZ3BCTmF0YXZ3@178.208.78.100:1080#%D0%9D%D0%B8%D0%B4%D0%B5%D1%80%D0%BB%D0%B0%D0%BD%D0%B4%D1%8B%20%F0%9F%87%B3%F0%9F%87%B1%20%20NL1%20

ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpmaERZUlJlSmE2R3pGZ3BCTmF0YXZ3@178.208.78.182:1080#%D0%9D%D0%B8%D0%B4%D0%B5%D1%80%D0%BB%D0%B0%D0%BD%D0%B4%D1%8B%20%F0%9F%87%B3%F0%9F%87%B1%20%20NL2

ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpmaERZUlJlSmE2R3pGZ3BCTmF0YXZ3@31.130.152.230:1080#%D0%9A%D0%B0%D0%B7%D0%B0%D1%85%D1%81%D1%82%D0%B0%D0%BD%20%F0%9F%87%B0%F0%9F%87%BF%20KZ%20%232

ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpmaERZUlJlSmE2R3pGZ3BCTmF0YXZ3@185.142.33.24:1080#%D0%93%D0%B5%D1%80%D0%BC%D0%B0%D0%BD%D0%B8%D1%8F%20%F0%9F%87%A9%F0%9F%87%AA%20DE%20%231

ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpmaERZUlJlSmE2R3pGZ3BCTmF0YXZ3@38.244.134.101:1080#%D0%9A%D0%B0%D0%B7%D0%B0%D1%85%D1%81%D1%82%D0%B0%D0%BD%20%F0%9F%87%B0%F0%9F%87%BF%20IS%20Hosting%20KZ%202%20%285566146968%29%20%5BShadowsocks%20-%20tcp%5D

ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpmaERZUlJlSmE2R3pGZ3BCTmF0YXZ3@38.180.146.124:1080#%D0%A1%D0%A8%D0%90%20%F0%9F%87%BA%F0%9F%87%B8%20IS%20Hosting%20USA%201%20%285566146968%29%20%5BShadowsocks%20-%20tcp%5D

ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpmaERZUlJlSmE2R3pGZ3BCTmF0YXZ3@188.116.26.183:1080#%D0%9D%D0%B8%D0%B4%D0%B5%D1%80%D0%BB%D0%B0%D0%BD%D0%B4%D1%8B%20%F0%9F%87%B3%F0%9F%87%B1%20IS%20Hosting%20NL1%20%285566146968%29%20%5BShadowsocks%20-%20tcp%5D

ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpmaERZUlJlSmE2R3pGZ3BCTmF0YXZ3@37.1.192.137:1080#%D0%93%D0%B5%D1%80%D0%BC%D0%B0%D0%BD%D0%B8%D1%8F%20%F0%9F%87%A9%F0%9F%87%AA%20IS%20Hosting%20DE1%20%285566146968%29%20%5BShadowsocks%20-%20tcp%5D

ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpmaERZUlJlSmE2R3pGZ3BCTmF0YXZ3@38.180.233.246:1080#%D0%9D%D0%B8%D0%B4%D0%B5%D1%80%D0%BB%D0%B0%D0%BD%D0%B4%D1%8B%20%F0%9F%87%B3%F0%9F%87%B1%20IS%20Hosting%20NL2%20%285566146968%29%20%5BShadowsocks%20-%20tcp%5D

ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpmaERZUlJlSmE2R3pGZ3BCTmF0YXZ3@38.244.134.110:1080#%D0%9A%D0%B0%D0%B7%D0%B0%D1%85%D1%81%D1%82%D0%B0%D0%BD%20%F0%9F%87%B0%F0%9F%87%BF%20IS%20Hosting%20KZ3%20%285566146968%29%20%5BShadowsocks%20-%20tcp%5D

ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpmaERZUlJlSmE2R3pGZ3BCTmF0YXZ3@38.180.112.141:1080#%D0%A2%D1%83%D1%80%D1%86%D0%B8%D1%8F%20%F0%9F%87%B9%F0%9F%87%B7%20IS%20hosting%20TR3%20%285566146968%29%20%5BShadowsocks%20-%20tcp%5D

ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpmaERZUlJlSmE2R3pGZ3BCTmF0YXZ3@37.252.22.236:1080#%D0%A0%D0%BE%D1%81%D1%81%D0%B8%D1%8F%20%F0%9F%87%B7%F0%9F%87%BA%20%231

vless://6984ee4c-bf3f-432e-a7da-7df1f01bcae9@178.208.78.100:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%9D%D0%B8%D0%B4%D0%B5%D1%80%D0%BB%D0%B0%D0%BD%D0%B4%D1%8B%20%F0%9F%87%B3%F0%9F%87%B1%20%20NL1%20

vless://6984ee4c-bf3f-432e-a7da-7df1f01bcae9@45.87.247.252:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%A0%D0%BE%D1%81%D1%81%D0%B8%D1%8F%20%F0%9F%87%B7%F0%9F%87%BA%20%20RU1%20

vless://6984ee4c-bf3f-432e-a7da-7df1f01bcae9@185.142.33.24:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%93%D0%B5%D1%80%D0%BC%D0%B0%D0%BD%D0%B8%D1%8F%20%F0%9F%87%A9%F0%9F%87%AA%20DE2%20

vless://6984ee4c-bf3f-432e-a7da-7df1f01bcae9@178.208.78.182:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%9D%D0%B8%D0%B4%D0%B5%D1%80%D0%BB%D0%B0%D0%BD%D0%B4%D1%8B%20%F0%9F%87%B3%F0%9F%87%B1%20NL2%20

vless://6984ee4c-bf3f-432e-a7da-7df1f01bcae9@31.130.152.230:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%9A%D0%B0%D0%B7%D0%B0%D1%85%D1%81%D1%82%D0%B0%D0%BD%20%F0%9F%87%B0%F0%9F%87%BF%20KZ2%20

vless://6984ee4c-bf3f-432e-a7da-7df1f01bcae9@178.208.78.182:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%9D%D0%B8%D0%B4%D0%B5%D1%80%D0%BB%D0%B0%D0%BD%D0%B4%D1%8B%20%F0%9F%87%B3%F0%9F%87%B1%20MC%20HOST%20NL2%20%285566146968%29%20%5BVLESS%20-%20tcp%5D

vless://6984ee4c-bf3f-432e-a7da-7df1f01bcae9@94.131.113.67:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%A0%D0%BE%D1%81%D1%81%D0%B8%D1%8F%20%F0%9F%87%B7%F0%9F%87%BA%20pq.hosting%20RU-1%20%285566146968%29%20%5BVLESS%20-%20tcp%5D

vless://6984ee4c-bf3f-432e-a7da-7df1f01bcae9@94.131.121.53:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%A0%D0%BE%D1%81%D1%81%D0%B8%D1%8F%20%F0%9F%87%B7%F0%9F%87%BA%20pq.hosting%20RU-2%20%285566146968%29%20%5BVLESS%20-%20tcp%5D

vless://6984ee4c-bf3f-432e-a7da-7df1f01bcae9@91.200.151.152:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%9A%D0%B0%D0%B7%D0%B0%D1%85%D1%81%D1%82%D0%B0%D0%BD%20%F0%9F%87%B0%F0%9F%87%BF%20timeweb-cloud%20KZ6%20%285566146968%29%20%5BVLESS%20-%20tcp%5D

vless://6984ee4c-bf3f-432e-a7da-7df1f01bcae9@38.180.104.128:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%A2%D1%83%D1%80%D1%86%D0%B8%D1%8F%20%F0%9F%87%B9%F0%9F%87%B7%20IS%20hosting%20TR2%20%285566146968%29%20%5BVLESS%20-%20tcp%5D

vless://6984ee4c-bf3f-432e-a7da-7df1f01bcae9@38.180.206.91:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%9A%D0%B0%D0%B7%D0%B0%D1%85%D1%81%D1%82%D0%B0%D0%BD%20%F0%9F%87%B0%F0%9F%87%BF%20IS%20hosting%20KZ7%20%285566146968%29%20%5BVLESS%20-%20tcp%5D

vless://6984ee4c-bf3f-432e-a7da-7df1f01bcae9@38.180.185.71:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%90%D1%80%D0%B3%D0%B5%D0%BD%D1%82%D0%B8%D0%BD%D0%B0%20%F0%9F%87%A6%F0%9F%87%B7%20IS%20hosting%20AG2%20%285566146968%29%20%5BVLESS%20-%20tcp%5D

vless://6984ee4c-bf3f-432e-a7da-7df1f01bcae9@38.244.134.101:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%9A%D0%B0%D0%B7%D0%B0%D1%85%D1%81%D1%82%D0%B0%D0%BD%20%F0%9F%87%B0%F0%9F%87%BF%20IS%20Hosting%20KZ%202%20%285566146968%29%20%5BVLESS%20-%20tcp%5D

vless://6984ee4c-bf3f-432e-a7da-7df1f01bcae9@38.180.146.124:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%A1%D0%A8%D0%90%20%F0%9F%87%BA%F0%9F%87%B8%20IS%20Hosting%20USA%201%20%285566146968%29%20%5BVLESS%20-%20tcp%5D

vless://6984ee4c-bf3f-432e-a7da-7df1f01bcae9@188.116.26.183:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%9D%D0%B8%D0%B4%D0%B5%D1%80%D0%BB%D0%B0%D0%BD%D0%B4%D1%8B%20%F0%9F%87%B3%F0%9F%87%B1%20IS%20Hosting%20NL1%20%285566146968%29%20%5BVLESS%20-%20tcp%5D

vless://6984ee4c-bf3f-432e-a7da-7df1f01bcae9@37.1.192.137:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%93%D0%B5%D1%80%D0%BC%D0%B0%D0%BD%D0%B8%D1%8F%20%F0%9F%87%A9%F0%9F%87%AA%20IS%20Hosting%20DE1%20%285566146968%29%20%5BVLESS%20-%20tcp%5D

vless://6984ee4c-bf3f-432e-a7da-7df1f01bcae9@38.180.233.246:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%9D%D0%B8%D0%B4%D0%B5%D1%80%D0%BB%D0%B0%D0%BD%D0%B4%D1%8B%20%F0%9F%87%B3%F0%9F%87%B1%20IS%20Hosting%20NL2%20%285566146968%29%20%5BVLESS%20-%20tcp%5D

vless://6984ee4c-bf3f-432e-a7da-7df1f01bcae9@38.244.134.110:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%9A%D0%B0%D0%B7%D0%B0%D1%85%D1%81%D1%82%D0%B0%D0%BD%20%F0%9F%87%B0%F0%9F%87%BF%20IS%20Hosting%20KZ3%20%285566146968%29%20%5BVLESS%20-%20tcp%5D

vless://6984ee4c-bf3f-432e-a7da-7df1f01bcae9@38.180.112.141:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%A2%D1%83%D1%80%D1%86%D0%B8%D1%8F%20%F0%9F%87%B9%F0%9F%87%B7%20IS%20hosting%20TR3%20%285566146968%29%20%5BVLESS%20-%20tcp%5D

vless://6984ee4c-bf3f-432e-a7da-7df1f01bcae9@37.252.22.236:2040?security=reality&type=tcp&headerType=&path=&host=&sni=tradingview.com&fp=chrome&pbk=9wfsGBdHj4v57u3U-YDUrqyHcBzZP_43xYXw0aT_UHE&sid=#%D0%A0%D0%BE%D1%81%D1%81%D0%B8%D1%8F%20%F0%9F%87%B7%F0%9F%87%BA%20%231%20vless'''