import struct
import wave
import os

def create_notification_sound():
    sample_rate = 44100
    duration = 0.3
    frequency = 800
    amplitude = 32767 * 0.5

    num_samples = int(sample_rate * duration)

    output = os.path.join(os.path.dirname(__file__), 'app', 'static', 'sounds')

    os.makedirs(output, exist_ok=True)

    filepath = os.path.join(output, 'notification.wav')

    with wave.open(filepath, 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)

        for i in range(num_samples):
            t = i / sample_rate
            envelope = 1.0 - (i / num_samples)
            sample = int(amplitude * envelope * (1 if (t * frequency * 2) % 1 < 0.5 else -1))
            wav_file.writeframes(struct.pack('<h', sample))

    print(f'Ses dosyasi olusturuldu: {filepath}')

if __name__ == '__main__':
    create_notification_sound()
