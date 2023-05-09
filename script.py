import time
from pathlib import Path

import gradio as gr
import azure.cognitiveservices.speech as speechsdk

from modules import chat, shared
from modules.html_generator import chat_html_wrapper

# Set your Azure Speech resource 'speech_key' and 'speech_region' here or in settings.json (see https://learn.microsoft.com/en-us/azure/cognitive-services/speech-service/get-started-text-to-speech?pivots=programming-language-python&tabs=windows%2Cterminal#set-environment-variables)
params = {
    'activate': True,
    'speaker': 'en-US-JennyNeural',
    'language': 'en-US',
    'speech_key': None,
    'speech_region': None,
    'show_text': False,
    'autoplay': True,
    'voice_pitch': 'default',
    'voice_speed': 'default',
    'local_cache_path': ''  # User can override the default cache path to something other via settings.json
}

current_params = params.copy()
# Find voices here: https://speech.microsoft.com/portal/voicegallery
voices = ['en-US-JennyNeural', 'en-US-AriaNeural', 'en-US-SaraNeural', 'en-US-DavisNeural', 'en-US-GuyNeural', 'en-US-TonyNeural']
# Learn about defining ssml properties (pitch, speed, etc.) here: https://learn.microsoft.com/en-us/azure/cognitive-services/speech-service/speech-synthesis-markup-voice#adjust-prosody
voice_pitches = ['default', 'x-low', 'low', 'medium', 'high', 'x-high']
voice_speeds = ['default', 'x-slow', 'slow', 'medium', 'fast', 'x-fast']

# Used for making text xml compatible, needed for voice pitch and speed control
table = str.maketrans({
    "<": "&lt;",
    ">": "&gt;",
    "&": "&amp;",
    "'": "&apos;",
    '"': "&quot;",
})


def xmlesc(txt):
    return txt.translate(table)


def load_synth():
    speech_config = speechsdk.SpeechConfig(subscription=params['speech_key'], region=params['speech_region'])
    audio_config = speechsdk.audio.AudioOutputConfig(use_default_speaker=True)
    speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    return speech_synthesizer


def remove_tts_from_history(name1, name2, mode, style):
    for i, entry in enumerate(shared.history['internal']):
        shared.history['visible'][i] = [shared.history['visible'][i][0], entry[1]]

    return chat_html_wrapper(shared.history['visible'], name1, name2, mode, style)


def toggle_text_in_history(name1, name2, mode, style):
    for i, entry in enumerate(shared.history['visible']):
        visible_reply = entry[1]
        if visible_reply.startswith('<audio'):
            if params['show_text']:
                reply = shared.history['internal'][i][1]
                shared.history['visible'][i] = [shared.history['visible'][i][0], f"{visible_reply.split('</audio>')[0]}</audio>\n\n{reply}"]
            else:
                shared.history['visible'][i] = [shared.history['visible'][i][0], f"{visible_reply.split('</audio>')[0]}</audio>"]

    return chat_html_wrapper(shared.history['visible'], name1, name2, mode, style)


def state_modifier(state):
    state['stream'] = False
    return state


def input_modifier(string):
    """
    This function is applied to your text inputs before
    they are fed into the model.
    """

    # Remove autoplay from the last reply
    if shared.is_chat() and len(shared.history['internal']) > 0:
        shared.history['visible'][-1] = [shared.history['visible'][-1][0], shared.history['visible'][-1][1].replace('controls autoplay>', 'controls>')]

    shared.processing_message = "*Is recording a voice message...*"
    return string


def output_modifier(string):
    """
    This function is applied to the model outputs.
    """

    global model, current_params, streaming_state

    for i in params:
        if params[i] != current_params[i]:
            model = load_synth()
            current_params = params.copy()
            break

    if not params['activate']:
        return string

    original_string = string
    string = tts_preprocessor.preprocess(string)

    if string == '':
        string = '*Empty reply, try regenerating*'
    else:
        output_file = Path(f'extensions/azure_tts/outputs/{shared.character}_{int(time.time())}.wav')
        ssml_tags=f'<voice name="{speaker_name}"><mstts:express-as style="hopeful" styledegree="2"><prosody pitch="{params['voice_pitch']}" rate="{params['voice_speed']}">'
        ssml_string  = f'<speak version="1.0" xmlns="https://www.w3.org/2001/10/synthesis" xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="{params["language"]}">{ssml_tags}{xmlesc(string)}</prosody></mstts:express-as></voice></speak>'

        speech_synthesis_result = model.speak_ssml_async(ssml_string).get()
    
        if speech_synthesis_result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            print(f'Outputing audio to {str(output_file)}')
            
            stream = speechsdk.AudioDataStream(speech_synthesis_result)
            stream.save_to_wav_file(output_file)
            
        elif speech_synthesis_result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = speech_synthesis_result.cancellation_details
            print("Speech synthesis canceled: {}".format(cancellation_details.reason))
            if cancellation_details.reason == speechsdk.CancellationReason.Error:
                if cancellation_details.error_details:
                    print("Error details: {}".format(cancellation_details.error_details))
                    print("Did you set the speech resource key and region values in azure_tts\script.py?")

        autoplay = 'autoplay' if params['autoplay'] else ''
        string = f'<audio src="file/{output_file.as_posix()}" controls {autoplay}></audio>'
        if params['show_text']:
            string += f'\n\n{original_string}'

    shared.processing_message = "*Is typing...*"
    return string


def setup():
    global model
    model = load_model()


def ui():
    # Gradio elements
    with gr.Accordion("Azure TTS"):
        with gr.Row():
            activate = gr.Checkbox(value=params['activate'], label='Activate TTS')
            autoplay = gr.Checkbox(value=params['autoplay'], label='Play TTS automatically')

        show_text = gr.Checkbox(value=params['show_text'], label='Show message text under audio player')
        voice = gr.Dropdown(value=params['speaker'], choices=voices, label='TTS voice')
        with gr.Row():
            v_pitch = gr.Dropdown(value=params['voice_pitch'], choices=voice_pitches, label='Voice pitch')
            v_speed = gr.Dropdown(value=params['voice_speed'], choices=voice_speeds, label='Voice speed')

        with gr.Row():
            convert = gr.Button('Permanently replace audios with the message texts')
            convert_cancel = gr.Button('Cancel', visible=False)
            convert_confirm = gr.Button('Confirm (cannot be undone)', variant="stop", visible=False)

    # Convert history with confirmation
    convert_arr = [convert_confirm, convert, convert_cancel]
    convert.click(lambda: [gr.update(visible=True), gr.update(visible=False), gr.update(visible=True)], None, convert_arr)
    convert_confirm.click(lambda: [gr.update(visible=False), gr.update(visible=True), gr.update(visible=False)], None, convert_arr)
    convert_confirm.click(remove_tts_from_history, [shared.gradio[k] for k in ['name1', 'name2', 'mode', 'chat_style']], shared.gradio['display'])
    convert_confirm.click(chat.save_history, shared.gradio['mode'], [], show_progress=False)
    convert_cancel.click(lambda: [gr.update(visible=False), gr.update(visible=True), gr.update(visible=False)], None, convert_arr)

    # Toggle message text in history
    show_text.change(lambda x: params.update({"show_text": x}), show_text, None)
    show_text.change(toggle_text_in_history, [shared.gradio[k] for k in ['name1', 'name2', 'mode', 'chat_style']], shared.gradio['display'])
    show_text.change(chat.save_history, shared.gradio['mode'], [], show_progress=False)

    # Event functions to update the parameters in the backend
    activate.change(lambda x: params.update({"activate": x}), activate, None)
    autoplay.change(lambda x: params.update({"autoplay": x}), autoplay, None)
    voice.change(lambda x: params.update({"speaker": x}), voice, None)
    v_pitch.change(lambda x: params.update({"voice_pitch": x}), v_pitch, None)
    v_speed.change(lambda x: params.update({"voice_speed": x}), v_speed, None)
