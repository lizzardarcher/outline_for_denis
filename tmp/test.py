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

