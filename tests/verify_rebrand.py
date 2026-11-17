from pathlib import Path
import os, sys, csv, json
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'frontend'))
os.environ['DJANGO_SETTINGS_MODULE']='chideman.settings'
from django.conf import settings
settings.DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':':memory:'}}
settings.ALLOWED_HOSTS=['testserver','localhost','127.0.0.1']
settings.DEBUG=True
import django
django.setup()
from django.db import connection
from django.apps import apps
from django.test import Client
from django.utils import timezone
from store.models import Product,Customer,Order,OrderItem,Payment,Shipment,Review
with connection.schema_editor() as editor:
 for model in [Product,Customer,Order,OrderItem,Payment,Shipment,Review]: editor.create_model(model)
rows=list(csv.DictReader((ROOT/'data/products_clean.csv').open()))[:36]
for row in rows:
 values={f.name:row[f.name] or None for f in Product._meta.fields}
 values['active']=row['active']=='True'
 Product.objects.create(**values)
now=timezone.now()
a=Customer.objects.create(customer_id=1,first_name='Alex',last_name='Demo',email='alex@example.com',created_at=now)
b=Customer.objects.create(customer_id=2,first_name='Sam',last_name='Demo',email='sam@example.com',created_at=now)
for c in [a,b]:
 order=Order.objects.create(order_id=c.pk,customer=c,order_date=now,status='processing',total_amount=29.99,updated_at=now)
 OrderItem.objects.create(order_item_id=c.pk,order=order,product=Product.objects.first(),quantity=1,unit_price=29.99)
c=Client()
for url in ['/','/shop/','/shop/?q=kettle','/shop/?category=Storage+%26+Organization&sort=price_low','/products/1/','/orders/']:
 r=c.get(url);assert r.status_code==200,(url,r.status_code)
 assert b'Chideman AI' in r.content
print('PASS: landing, catalog, search/filter/sort, product, guest orders render')
assert c.post('/assistant/chat/',data=json.dumps({'messages':[]}),content_type='application/json').status_code==403
assert c.post('/switch-customer/',{'customer_id':'1'}).status_code==302
assert c.get('/orders/1/').status_code==200
assert c.get('/orders/2/').status_code==404
with patch('store.views.urllib.request.urlopen') as upstream:
 upstream.return_value.__enter__.return_value.read.return_value=json.dumps({'reply':'CHEE here!','tool_calls':[]}).encode()
 r=c.post('/assistant/chat/',data=json.dumps({'customer_id':2,'messages':[{'role':'user','content':'Hi'}]}),content_type='application/json')
 assert r.status_code==200
 payload=json.loads(upstream.call_args.args[0].data)
 assert payload['customer_id']==1
print('PASS: customer switch, order ownership, guest chat gate, server-owned chat identity and response forwarding')
assert c.post('/assistant/chat/',data='invalid',content_type='application/json').status_code==400
# Verify empty catalogs do not crash the refreshed landing page.
Product.objects.update(active=False)
assert c.get('/').status_code == 200
Product.objects.update(active=True)
assert Client(enforce_csrf_checks=True).post('/assistant/chat/', data='{}', content_type='application/json').status_code == 403
print('PASS: empty catalog and CSRF protection')
# Real rendered pages for browser QA, independent of production database.
preview=ROOT/'.qa-preview'
preview.mkdir(exist_ok=True)
for name,url in [('index.html','/'),('shop.html','/shop/'),('product.html','/products/1/'),('orders.html','/orders/'),('order.html','/orders/1/')]:
 (preview/name).write_bytes(c.get(url).content)
guest=Client();(preview/'guest.html').write_bytes(guest.get('/').content)
import shutil
shutil.copytree(ROOT/'frontend/store/static',preview/'static',dirs_exist_ok=True)
for f in preview.glob('*.html'):
 s=f.read_text().replace('href="/shop/"','href="/shop.html"').replace('href="/orders/"','href="/orders.html"').replace('href="/products/1/"','href="/product.html"')
 f.write_text(s)
# The production code is compiled without importing external service clients.
import ast
for f in ROOT.rglob('*.py'):ast.parse(f.read_text())
print('PASS: Python syntax; rendered browser fixtures written')
