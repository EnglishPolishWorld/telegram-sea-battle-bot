import base64, io, json, os, random, sqlite3, time, urllib.request
from collections import Counter
from PIL import Image

RANKS=["2","3","4","5","6","7","8","9","10","J","Q","K","A"]
ASSETS=os.path.join(os.path.dirname(__file__),"assets")

def prepare_assets():
 for name in ("table","dog_states","hands_cards"):
  png=os.path.join(ASSETS,name+".png")
  if not os.path.exists(png):
   with open(os.path.join(ASSETS,name+".png.b64")) as src, open(png,"wb") as dst: dst.write(base64.b64decode(src.read()))

class API:
 def __init__(self,t): self.u=f"https://api.telegram.org/bot{t}/"
 def call(self,m,p=None):
  q=urllib.request.Request(self.u+m,json.dumps(p or {}).encode(),{"Content-Type":"application/json"})
  with urllib.request.urlopen(q,timeout=45) as r: x=json.loads(r.read())
  if not x["ok"]: raise RuntimeError(x)
  return x["result"]
 def multipart(self,m,fields,data):
  b="----dogcards"; body=b""
  for k,v in fields.items(): body+=f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
  body+=f"--{b}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"scene.png\"\r\nContent-Type: image/png\r\n\r\n".encode()+data+f"\r\n--{b}--\r\n".encode()
  q=urllib.request.Request(self.u+m,body,{"Content-Type":f"multipart/form-data; boundary={b}"})
  with urllib.request.urlopen(q,timeout=60) as r: x=json.loads(r.read())
  if not x["ok"]: raise RuntimeError(x)
  return x["result"]

class Store:
 def __init__(self,path):
  self.db=sqlite3.connect(path); self.db.execute("CREATE TABLE IF NOT EXISTS games(id TEXT PRIMARY KEY,user_id INTEGER,state TEXT)")
  self.db.execute("CREATE TABLE IF NOT EXISTS stats(user_id INTEGER PRIMARY KEY,wins INTEGER DEFAULT 0,losses INTEGER DEFAULT 0,streak INTEGER DEFAULT 0,best INTEGER DEFAULT 0)"); self.db.commit()
 def save(self,g): self.db.execute("INSERT OR REPLACE INTO games VALUES(?,?,?)",(g["id"],g["uid"],json.dumps(g))); self.db.commit()
 def get(self,i):
  r=self.db.execute("SELECT state FROM games WHERE id=?",(i,)).fetchone(); return json.loads(r[0]) if r else None
 def finish(self,g,win):
  self.db.execute("INSERT OR IGNORE INTO stats(user_id) VALUES(?)",(g["uid"],))
  self.db.execute("UPDATE stats SET wins=wins+?,losses=losses+?,streak=CASE WHEN ? THEN streak+1 ELSE 0 END,best=MAX(best,CASE WHEN ? THEN streak+1 ELSE best END) WHERE user_id=?",(win,not win,win,win,g["uid"]));self.db.commit()

def books(hand):
 c=Counter(hand); made=[r for r,n in c.items() if n==4]
 for r in made:
  for _ in range(4): hand.remove(r)
 return made

def new_game(uid):
 deck=[r for r in RANKS for _ in range(4)];random.shuffle(deck)
 p=[deck.pop() for _ in range(7)];d=[deck.pop() for _ in range(7)]
 return {"id":hex(random.getrandbits(40))[2:],"uid":uid,"p":p,"d":d,"deck":deck,"pb":books(p),"db":books(d),"m":"Ваш ход. Выберите ранг.","pose":0,"start":int(time.time()),"done":False}

def scene(pose):
 bg=Image.open(os.path.join(ASSETS,"table.png")).convert("RGBA")
 sheet=Image.open(os.path.join(ASSETS,"dog_states.png")).convert("RGBA")
 w,h=sheet.width//4,sheet.height//2; dog=sheet.crop(((pose%4)*w,(pose//4)*h,(pose%4+1)*w,(pose//4+1)*h))
 dog.thumbnail((bg.width//3,bg.height//2)); bg.alpha_composite(dog,((bg.width-dog.width)//2,bg.height//12))
 out=io.BytesIO();bg.convert("RGB").save(out,"PNG",optimize=True);return out.getvalue()

def markup(g):
 buttons=[[{"text":r,"callback_data":f"ask:{g['id']}:{r}"} for r in sorted(set(g["p"]),key=RANKS.index)[i:i+6]] for i in range(0,len(set(g["p"])),6)]
 buttons.append([{"text":"🔄 Новая игра","callback_data":"new"},{"text":"📊 Статистика","callback_data":"stats"}])
 return json.dumps({"inline_keyboard":buttons},ensure_ascii=False)

def caption(g):
 return f"🐶 КАРТОЧНЫЙ ПЁС\n\n{g['m']}\n\n🫵 Ваши карты: {' '.join(g['p']) or '—'}\n📚 Ваши наборы: {len(g['pb'])}\n🐾 Карт у пса: {len(g['d'])}\n📚 Наборы пса: {len(g['db'])}\n🂠 В колоде: {len(g['deck'])}"

def dog_turn(g):
 if not g["d"] or not g["p"]: return
 r=random.choice(g["d"])
 got=[x for x in g["p"] if x==r]
 if got:
  g["p"]=[x for x in g["p"] if x!=r];g["d"]+=got;g["m"]=f"Пёс забрал у вас {r}.";g["pose"]=1
 else:
  if g["deck"]: g["d"].append(g["deck"].pop())
  g["m"]=f"Пёс спросил {r}, но пошёл рыбачить.";g["pose"]=2
 g["db"]+=books(g["d"])

def check(g,store):
 if (not g["deck"] and (not g["p"] or not g["d"])) or len(g["pb"])+len(g["db"])==13:
  win=len(g["pb"])>len(g["db"]);g["done"]=True;g["pose"]=7 if not win else 6
  g["m"]=f"{'Вы победили!' if win else 'Пёс победил!'} Счёт {len(g['pb'])}:{len(g['db'])}";store.finish(g,win)

def main():
 prepare_assets()
 token=os.getenv("BOT_TOKEN")
 if not token: raise SystemExit("BOT_TOKEN required")
 api=API(token);store=Store(os.getenv("DATABASE_PATH","cards.sqlite3"));off=0
 api.call("setMyCommands",{"commands":[{"command":"start","description":"Играть с Карточным Псом"},{"command":"creator","description":"Создатель бота"}]})
 while True:
  try:
   for u in api.call("getUpdates",{"offset":off,"timeout":30,"allowed_updates":["message","callback_query"]}):
    off=u["update_id"]+1
    if "message" in u:
     m=u["message"];txt=m.get("text","").split("@")[0]
     if txt=="/creator": api.call("sendMessage",{"chat_id":m["chat"]["id"],"text":"Создатель бота — @eternall_dog\nПо всем вопросам и предложениям пишите ему."});continue
     if txt=="/start":
      g=new_game(m["from"]["id"]);store.save(g);api.multipart("sendPhoto",{"chat_id":m["chat"]["id"],"caption":caption(g),"reply_markup":markup(g)},scene(g["pose"]))
    elif "callback_query" in u:
     q=u["callback_query"];data=q["data"];api.call("answerCallbackQuery",{"callback_query_id":q["id"]})
     if data=="new": g=new_game(q["from"]["id"])
     elif data=="stats":
      r=store.db.execute("SELECT wins,losses,streak,best FROM stats WHERE user_id=?",(q["from"]["id"],)).fetchone() or (0,0,0,0)
      api.call("answerCallbackQuery",{"callback_query_id":q["id"],"text":f"Победы {r[0]} · Поражения {r[1]} · Серия {r[2]} · Рекорд {r[3]}","show_alert":True});continue
     else:
      _,gid,r=data.split(":");g=store.get(gid)
      if not g or g["uid"]!=q["from"]["id"]: continue
      got=[x for x in g["d"] if x==r]
      if got:g["d"]=[x for x in g["d"] if x!=r];g["p"]+=got;g["m"]=f"Пёс отдал вам {len(got)} карт ранга {r}!";g["pose"]=5
      else:
       drawn=g["deck"].pop() if g["deck"] else None
       if drawn:g["p"].append(drawn)
       g["m"]=f"Нет {r}. Рыбачьте!";g["pose"]=4
      g["pb"]+=books(g["p"]);dog_turn(g)
     check(g,store);store.save(g)
     media=json.dumps({"type":"photo","media":"attach://photo","caption":caption(g)},ensure_ascii=False)
     api.multipart("editMessageMedia",{"chat_id":q["message"]["chat"]["id"],"message_id":q["message"]["message_id"],"media":media,"reply_markup":markup(g)},scene(g["pose"]))
  except Exception as e: print(type(e).__name__,e);time.sleep(3)
if __name__=="__main__":main()
