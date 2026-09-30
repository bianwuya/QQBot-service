import io
import tempfile
import unittest
from pathlib import Path
from PIL import Image

from image_input import IMAGE_PIXELS_LIMIT,find_refs,read_image
from protocol import image_refs,normalize
from safe_net import Rejected

FID='a'*32+'.png'

class FakeOneBot:
    def __init__(self,message=None,result=None):self.calls=[];self.message=message or {};self.result=result or {}
    def call(self,action,payload,timeout=None):
        self.calls.append((action,payload))
        return self.message if action=='get_msg' else self.result

class InboundImageTest(unittest.TestCase):
    def test_normalize_current_and_only_structured_image(self):
        raw={'post_type':'message','user_id':12345,'self_id':67890,'message_type':'group',
             'group_id':111111,'message_id':999,'message':[{'type':'at','data':{'qq':'67890'}},
                {'type':'text','data':{'text':'[CQ:image,file='+FID+'] 看这张图'}},
                {'type':'image','data':{'file':FID,'url':'http://unsafe.invalid/'}}]}
        event=normalize(raw)
        self.assertEqual(event['image_refs'],[{'file':FID}]);self.assertEqual(event['image_count'],1)
        self.assertEqual(image_refs([{'type':'image','data':{'file':'file:///etc/passwd'}},
            {'type':'image','data':{'file':'../config.json'}},
            {'type':'text','data':{'text':'[CQ:image,file='+FID+']'}}]),[])
    def test_empty_mention_with_reply_normalizes(self):
        raw={'post_type':'message','user_id':12345,'self_id':67890,'message_type':'group',
             'group_id':111111,'message_id':999,'message':[{'type':'at','data':{'qq':'67890'}},
                {'type':'reply','data':{'id':'1000'}}]}
        self.assertEqual(normalize(raw)['reply_id'],'1000')
    def test_same_group_quote_and_preference(self):
        event={'scope':'g:111111','owner':'12345','reply_id':'1000','text':'这张图是什么','image_count':0}
        source={'message_type':'group','group_id':111111,'user_id':54321,
                'message':[{'type':'image','data':{'file':FID}}]}
        ob=FakeOneBot(message=source)
        self.assertEqual(find_refs(event,ob),[{'file':FID}]);self.assertEqual(len(ob.calls),1)
        event.update(image_count=1,image_refs=[{'file':FID}])
        self.assertEqual(find_refs(event,ob),[{'file':FID}]);self.assertEqual(len(ob.calls),1)
    def test_reject_cross_group_or_private_source(self):
        for source in ({'message_type':'group','group_id':222222},
                       {'message_type':'private','user_id':12345}):
            with self.subTest(source=source),self.assertRaises(Rejected):
                find_refs({'scope':'g:111111','owner':'12345','reply_id':'1000','image_count':0},FakeOneBot(source))
        for source in ({'message_type':'private','user_id':11111},
                       {'message_type':'group','group_id':12345}):
            with self.subTest(source=source),self.assertRaises(Rejected):
                find_refs({'scope':'p:12345','owner':'12345','reply_id':'1000','image_count':0},FakeOneBot(source))
    def test_private_same_peer_and_no_photo_honesty(self):
        e={'scope':'p:12345','owner':'12345','reply_id':'1000','image_count':0,'text':'看这张图'}
        ob=FakeOneBot({'message_type':'private','user_id':12345,
            'message':[{'type':'image','data':{'file':FID}}]})
        self.assertEqual(find_refs(e,ob),[{'file':FID}])
        ob=FakeOneBot({'message_type':'private','user_id':12345,'message':[]})
        with self.assertRaisesRegex(Rejected,'没有可读取'):find_refs(e,ob)
    def test_private_bot_sent_photo_needs_peer_history(self):
        e={'scope':'p:12345','owner':'12345','self_id':'67890','reply_id':'1000','image_count':0,'text':'看这张图'}
        image=[{'type':'image','data':{'file':FID}}]
        source={'message_type':'private','user_id':67890,'message':image}
        history={'messages':[{'message_id':1000,'message_type':'private','user_id':67890,'message':image}]}
        ob=FakeOneBot(source,history)
        self.assertEqual(find_refs(e,ob),[{'file':FID}]);self.assertEqual([x[0] for x in ob.calls],['get_msg','get_friend_msg_history'])
        ob=FakeOneBot(source,{'messages':[]})
        with self.assertRaisesRegex(Rejected,'同一会话'):find_refs(e,ob)
        bad={'messages':[{'message_id':1000,'message_type':'private','user_id':67890,'message':
                         [{'type':'image','data':{'file':'b'*32+'.png'}}]}]}
        with self.assertRaises(Rejected):find_refs(e,FakeOneBot(source,bad))
    def test_no_unsafe_get_image_call(self):
        with tempfile.TemporaryDirectory() as temp:
            ob=FakeOneBot(result={'file':str(Path(temp)/'x')})
            with self.assertRaises(Rejected):read_image(ob,'../secret',[temp],Path(temp)/'out.jpg')
            self.assertEqual(ob.calls,[])
    def test_local_cache_roundtrip_and_no_exif(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cache=root/'cache';cache.mkdir()
            Image.new('RGB',(50,30),'cyan').save(cache/'sample.png')
            ob=FakeOneBot(result={'file':str(cache/'sample.png'),'url':'http://unsafe.invalid/'})
            result=read_image(ob,FID,[cache],root/'output.jpg')
            self.assertEqual(ob.calls[0][0],'get_image')
            with Image.open(result) as out:self.assertEqual(out.size,(50,30));self.assertEqual(out.format,'JPEG');self.assertFalse(out.getexif())
    def test_reject_outside_allowlist_and_bad_content_and_pixels(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cache=root/'cache';cache.mkdir();outside=root/'secret.png'
            outside.write_bytes(b'not really an image')
            with self.assertRaisesRegex(Rejected,'授权缓存'):read_image(FakeOneBot(result={'file':str(outside)}),FID,[cache],root/'output.jpg')
            (cache/'bad.png').write_bytes(b'not really an image')
            with self.assertRaisesRegex(Rejected,'安全解码'):read_image(FakeOneBot(result={'file':str(cache/'bad.png')}),FID,[cache],root/'output.jpg')
            Image.new('RGB',(4000,4000),'white').save(cache/'large.png')
            with self.assertRaises(Rejected):read_image(FakeOneBot(result={'file':str(cache/'large.png')}),FID,[cache],root/'output.jpg')
            if hasattr((cache/'link.png'),'symlink_to'):
                try:(cache/'link.png').symlink_to(outside)
                except OSError:pass  # Windows ACL may forbid unprivileged symlinks.
                else:
                    with self.assertRaises(Rejected):read_image(FakeOneBot(result={'file':str(cache/'link.png')}),FID,[cache],root/'output.jpg')

if __name__=='__main__':unittest.main()
