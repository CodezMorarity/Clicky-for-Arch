"""Opt-in live desktop/STT/Ollama/TTS check; opens a temporary test canvas.

Run manually from a Hyprland session; never collected by pytest.
"""
import sys,os,tempfile,asyncio,io,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['CLICKY_CONFIG_FILE']=tempfile.mktemp(prefix='clicky-e2e-config-')
os.environ['CLICKY_DATA_DIR']=tempfile.mkdtemp(prefix='clicky-e2e-data-')
os.environ['CLICKY_ACTIVE_LLM']='ollama'
from desktop import prepare_qt
prepare_qt()
async def input_audio():
 import edge_tts,numpy as np
 from audio.playback import decode_mp3_to_pcm
 from audio.capture import resample_pcm
 buf=io.BytesIO()
 async for chunk in edge_tts.Communicate('What color is the circle on my screen? Answer in one sentence.','en-US-AriaNeural').stream():
  if chunk['type']=='audio':buf.write(chunk['data'])
 pcm,sr=decode_mp3_to_pcm(buf.getvalue())
 return resample_pcm((np.clip(pcm,-1,1)*32767).astype(np.int16).tobytes(),sr)
audio=asyncio.run(input_audio())
from PyQt6.QtWidgets import QApplication,QWidget
from PyQt6.QtCore import Qt,QTimer
from PyQt6.QtGui import QPainter,QColor,QFont
from desktop.display import attach
from desktop.hyprland import query,command
from companion_manager import CompanionManager
from ui.overlay import CursorOverlay
from ui.panel import CompanionPanel,AppState
import json
class Canvas(QWidget):
 def paintEvent(self,event):
  p=QPainter(self);p.fillRect(self.rect(),QColor('white'));p.setBrush(QColor('red'));p.setPen(Qt.PenStyle.NoPen)
  p.drawEllipse(self.width()//2-160,self.height()//2-160,320,320)
  p.setPen(QColor('black'));p.setFont(QFont('Sans Serif',24));p.drawText(40,70,'Clicky verification');p.end()
class TestInput:
 def start_recording(self):pass
 def stop_recording(self):return audio
 def stop(self):pass
app=QApplication(['clicky-verification']);app.setQuitOnLastWindowClosed(False);attach(app)
canvas=Canvas();canvas.setWindowTitle('Clicky verification');canvas.showFullScreen()
manager=CompanionManager();manager._listener=TestInput();manager._web_search_enabled=False;manager._multilang=False;manager._journal_enabled=False
panel=CompanionPanel();overlay=CursorOverlay();overlay.show()
manager.sig_response_chunk.connect(panel.append_response_chunk)
manager.sig_point_at.connect(overlay.point_at);manager.sig_draw.connect(overlay.add_shape);manager.sig_clear_drawings.connect(overlay.clear_annotations)
answers=[];errors=[];states=[];started=time.monotonic();status=1
manager.sig_response_done.connect(lambda t: (answers.append(t),print('answer',repr(t),flush=True)))
def state(value):
 states.append(value.name);panel.set_state(value);print('state',value.name,flush=True)
 if value==AppState.IDLE and (answers or errors):QTimer.singleShot(150,app.quit)
manager.sig_state_changed.connect(state)
manager.sig_error.connect(lambda e:(errors.append(e),print('error',e,flush=True)))
def begin():
 try:
  own=[c for c in query('clients') if c.get('pid')==os.getpid() and c.get('title')=='Clicky verification']
  if own:command('dispatch','hl.dsp.focus({ window = '+json.dumps('address:'+own[0]['address'])+' })')
  manager.on_hotkey_press();manager._hotkey_pressed_at=time.monotonic()-1;manager.on_hotkey_release()
 except Exception as exc:
  errors.append(str(exc));print('begin error',exc,flush=True);app.quit()
QTimer.singleShot(1000,begin);QTimer.singleShot(150000,app.quit)
try:app.exec()
finally:manager.shutdown();overlay.close();canvas.close();panel.close()
status=0 if not errors and answers and 'red' in answers[-1].lower() and states[-1]=='IDLE' and not manager._thread.is_alive() else 1
print('end-to-end', 'PASS' if status==0 else 'FAIL','seconds',round(time.monotonic()-started,1),'states',states,flush=True)
sys.exit(status)
