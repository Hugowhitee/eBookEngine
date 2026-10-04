"""Small document-first Windows UI (stdlib ttk, no browser/remote services)."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import queue
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog,messagebox,ttk
from tkinter.scrolledtext import ScrolledText

from PIL import Image,ImageTk
from lxml import html

from .core import sniff, EpubSource, ChangeSession, DocumentError, atomic_save
from .pdf_engine import (inspect_pdf,page_image,searchable_pdf,has_tesseract,has_docling,pdf_metadata)
from .conversion import reconstruct_pdf_epub
from . import local_ai,layout_runtime


class Viewer(ttk.Frame):
    def __init__(self,parent,title):
        super().__init__(parent)
        ttk.Label(self,text=title,style='Section.TLabel').pack(anchor='w',padx=8,pady=(8,5))
        self.body=ttk.Frame(self);self.body.pack(fill='both',expand=True)
        self.text=ScrolledText(self.body,wrap='word',state='disabled',font=('Segoe UI',11),borderwidth=0,
                               padx=13,pady=10,relief='flat')
        self.canvas=tk.Canvas(self.body,highlightthickness=0,background='#606872')
        self.scrollbar=ttk.Scrollbar(self.body,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.photo=None
        self.show_text('Open an EPUB or PDF to preview the document.')

    def clear(self):
        self.text.pack_forget();self.canvas.pack_forget();self.scrollbar.pack_forget()
        self.photo=None

    def show_text(self,content):
        self.clear();self.text.pack(fill='both',expand=True)
        self.text.config(state='normal');self.text.delete('1.0','end')
        self.text.insert('end',content)
        self.text.config(state='disabled')

    def show_image(self,img):
        self.clear()
        self.scrollbar.pack(side='right',fill='y')
        self.canvas.pack(side='left',fill='both',expand=True)
        self.photo=ImageTk.PhotoImage(img)
        self.canvas.delete('all')
        self.canvas.create_image(8,8,anchor='nw',image=self.photo)
        self.canvas.configure(scrollregion=(0,0,img.width+16,img.height+16))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('eBookEngine')
        self.geometry('1260x795');self.minsize(930,625)
        self._style()
        self.path=None;self.kind=None;self.source=None;self.session=None
        self.candidate=None;self.result_kind=None;self.temp_path=None
        self.page_index=0;self.chapter_index=0;self.zoom=1.1;self.has_cover=False
        self.pdf_info=None;self.custom_pdf_edits={};self._photos=[]
        self.running=False;self.cancel=threading.Event();self.events=queue.Queue()
        self._suspend=False
        self.build_ui();self._refresh_controls()
        self.after(80,self._poll)

    def _style(self):
        style=ttk.Style(self)
        if 'vista' in style.theme_names():style.theme_use('vista')
        elif 'clam' in style.theme_names():style.theme_use('clam')
        style.configure('.',font=('Segoe UI',10))
        style.configure('Section.TLabel',font=('Segoe UI Semibold',10))
        style.configure('Strong.TButton',font=('Segoe UI Semibold',10),padding=(9,5))
        style.configure('TButton',padding=(7,4))
        style.configure('TEntry',padding=4)

    def build_ui(self):
        bar=ttk.Frame(self,padding=(12,10))
        bar.pack(fill='x')
        self.open_btn=ttk.Button(bar,text='Open…',command=self.open_dialog)
        self.open_btn.pack(side='left')
        ttk.Label(bar,text='Output:',padding=(14,0,6,0)).pack(side='left')
        self.output=tk.StringVar()
        self.output_control=ttk.Combobox(bar,textvariable=self.output,width=22,state='readonly')
        self.output_control.pack(side='left');self.output_control.bind('<<ComboboxSelected>>',lambda _:self._output_changed())
        self.improve_btn=ttk.Button(bar,text='Improve',command=self.improve,style='Strong.TButton')
        self.improve_btn.pack(side='left',padx=(11,0))
        self.save_btn=ttk.Button(bar,text='Save as…',command=self.save)
        self.save_btn.pack(side='left',padx=(7,0))
        self.undo_btn=ttk.Button(bar,text='Undo',command=self.undo)
        self.undo_btn.pack(side='left',padx=(19,0))
        self.redo_btn=ttk.Button(bar,text='Redo',command=self.redo)
        self.redo_btn.pack(side='left',padx=(5,0))
        self.tools_btn=ttk.Menubutton(bar,text='Extra')
        menu=tk.Menu(self.tools_btn,tearoff=False)
        menu.add_command(label='Local OCR / AI setup…',command=self.setup_engines)
        menu.add_command(label='Suggest description with AI…',command=self.suggest_description)
        self.tools_btn.configure(menu=menu);self.tools_btn.pack(side='right')
        self.info_var=tk.StringVar(value='PDF, EPUB and KEPUB-EPUB are supported.')
        ttk.Label(self,textvariable=self.info_var,padding=(14,5,10,8)).pack(fill='x')
        paned=ttk.Panedwindow(self,orient='horizontal');paned.pack(fill='both',expand=True,padx=12,pady=(0,4))
        nav=ttk.Frame(paned,width=172);paned.add(nav,weight=0)
        ttk.Label(nav,text='Contents',style='Section.TLabel').pack(anchor='w',pady=(7,5))
        self.navigation=tk.Listbox(nav,exportselection=False,selectmode='single',font=('Segoe UI',10),
                                   relief='solid',borderwidth=1,activestyle='none',width=23)
        self.navigation.pack(fill='both',expand=True)
        self.navigation.bind('<<ListboxSelect>>',self.jump)
        center=ttk.Frame(paned);paned.add(center,weight=5)
        navrow=ttk.Frame(center);navrow.pack(fill='x',pady=(0,4))
        ttk.Button(navrow,text='‹',width=4,command=lambda:self.shift(-1)).pack(side='left')
        self.position=tk.StringVar(value='—')
        ttk.Label(navrow,textvariable=self.position,width=18).pack(side='left',padx=6)
        ttk.Button(navrow,text='›',width=4,command=lambda:self.shift(1)).pack(side='left')
        ttk.Label(navrow,text='Zoom').pack(side='left',padx=(15,3))
        ttk.Button(navrow,text='−',width=3,command=lambda:self.resize(-.15)).pack(side='left')
        ttk.Button(navrow,text='+',width=3,command=lambda:self.resize(.15)).pack(side='left',padx=(4,0))
        self.searchtext=tk.StringVar()
        ttk.Entry(navrow,textvariable=self.searchtext,width=15).pack(side='left',padx=(14,2),fill='x',expand=True)
        ttk.Button(navrow,text='Find',command=self.search).pack(side='left')
        views=ttk.Panedwindow(center,orient='horizontal');views.pack(fill='both',expand=True)
        self.original_view=Viewer(views,'Original');views.add(self.original_view,weight=1)
        self.result_view=Viewer(views,'Result — after Improve');views.add(self.result_view,weight=1)
        inspector=ttk.Frame(paned,width=248);paned.add(inspector,weight=0)
        ttk.Label(inspector,text='Changes',style='Section.TLabel').pack(anchor='w',pady=(7,5))
        self.changelist=tk.Listbox(inspector,height=8,exportselection=False,font=('Segoe UI',10),
                                    relief='solid',borderwidth=1,width=28)
        self.changelist.pack(fill='x')
        self.changelist.bind('<Double-Button-1>',lambda _:self.toggle_change())
        ttk.Button(inspector,text='Apply / Revert selected',command=self.toggle_change).pack(fill='x',pady=(5,12))
        ttk.Separator(inspector).pack(fill='x',pady=(0,8))
        ttk.Label(inspector,text='Book details',style='Section.TLabel').pack(anchor='w',pady=(0,5))
        self.meta={}
        for text,field in [('Title','title'),('Author','author')]:
            ttk.Label(inspector,text=text).pack(anchor='w')
            var=tk.StringVar();self.meta[field]=var
            ttk.Entry(inspector,textvariable=var).pack(fill='x',pady=(2,7))
        ttk.Label(inspector,text='Description').pack(anchor='w')
        self.description=tk.Text(inspector,height=6,width=29,wrap='word',font=('Segoe UI',9),relief='solid',borderwidth=1)
        self.description.pack(fill='x',pady=(2,7))
        ttk.Label(inspector,text='Cover image').pack(anchor='w')
        self.cover=tk.StringVar()
        self.coverbox=ttk.Combobox(inspector,textvariable=self.cover,state='readonly')
        self.coverbox.pack(fill='x',pady=(2,6))
        ttk.Button(inspector,text='Apply book details',command=self.apply_metadata).pack(fill='x')
        self.details_note=ttk.Label(inspector,text='Edits are separate from the original.',wraplength=235,foreground='#666666')
        self.details_note.pack(anchor='w',pady=(12,0))
        status=ttk.Frame(self,padding=(12,8));status.pack(fill='x')
        self.status=tk.StringVar(value='Ready')
        ttk.Label(status,textvariable=self.status,width=52).pack(side='left')
        self.progress=ttk.Progressbar(status,mode='determinate',length=170,maximum=100)
        self.progress.pack(side='right',padx=(8,2))
        self.cancel_btn=ttk.Button(status,text='Cancel',command=self.cancel.set)
        self.cancel_btn.pack(side='right')
        self.cancel_btn.state(['disabled'])
        self.bind('<Control-o>',lambda _:self.open_dialog())
        self.bind('<Control-Shift-S>',lambda _:self.save())

    def _refresh_controls(self):
        busy=self.running
        for button in (self.open_btn,self.improve_btn,self.save_btn,self.undo_btn,self.redo_btn):
            button.state(['disabled'] if busy else ['!disabled'])
        if not self.path:self.improve_btn.state(['disabled'])
        if self.candidate is None:self.save_btn.state(['disabled'])
        self.cancel_btn.state(['!disabled'] if busy else ['disabled'])
        self.output_control.config(state='disabled' if busy else 'readonly')
        if not self.session or not self.session._history:self.undo_btn.state(['disabled'])
        if not self.session or not self.session._redo:self.redo_btn.state(['disabled'])
        if self.kind=='PDF' and self.output.get()=='Searchable PDF' and self.pdf_info and all(self.pdf_info.has_text):
            self.improve_btn.state(['disabled'])
        if self.kind=='PDF' and self.output.get()=='EPUB (complex PDF)' and not has_docling():
            self.improve_btn.state(['disabled'])

    def open_dialog(self):
        path=filedialog.askopenfilename(title='Open a book or PDF',
            filetypes=[('EPUB and PDF','*.epub *.pdf'),('All files','*.*')])
        if path:self.open_file(path)

    def open_file(self,path):
        if self.running:return
        try:
            kind=sniff(path)
            if kind=='EPUB':
                source=EpubSource(path);info=source.info;self.session=ChangeSession(source)
                self.pdf_info=None
                choices=('Clean EPUB',)
                names=list(source.navnames)
            else:
                info=inspect_pdf(path);source=None;self.session=None;self.pdf_info=info
                choices=('Searchable PDF','EPUB (complex PDF)') if any(not t for t in info.has_text) else ('PDF (metadata)','EPUB (complex PDF)')
                names=[f'Page {i+1}' for i in range(info.pages)]
            self.path=Path(path);self.kind=kind;self.source=source;self.candidate=None
            self.has_cover=bool(kind=='EPUB' and info.covers)
            self.result_kind=None;self.page_index=0;self.chapter_index=(-1 if self.has_cover else 0)
            self.output_control['values']=choices;self.output.set(choices[0])
            self.navigation.delete(0,'end')
            if self.has_cover:self.navigation.insert('end','Cover')
            for name in names:self.navigation.insert('end',name)
            self.navigation.selection_set(0)
            title=(info.title if kind=='EPUB' else info.title) or self.path.stem
            author=(info.author if kind=='EPUB' else info.author) or 'Unknown author'
            self.info_var.set(f'{self.path.name}   ·   {kind}   ·   {len(names)} {"sections" if kind=="EPUB" else "pages"}   ·   {author}')
            self.meta['title'].set(title);self.meta['author'].set(info.author or '')
            self.description.config(state='normal');self.description.delete('1.0','end')
            if kind=='EPUB':self.description.insert('1.0',info.description)
            self.coverbox['values']=info.covers if kind=='EPUB' else ()
            self.cover.set(next((c.after for c in self.session.changes.values() if c.field=='cover' and c.enabled), info.current_cover or '') if kind=='EPUB' else '')
            if kind=='PDF':self.coverbox.state(['disabled']);self.description.config(state='disabled')
            else:self.coverbox.state(['!disabled']);self.description.config(state='normal')
            self._fill_changes();self._render();self.status.set(f'{kind} opened. Source unchanged.')
            if kind=='EPUB' and info.warnings:
                self.details_note.config(text=' · '.join(info.warnings)[:220])
            else:self.details_note.config(text='Edits are separate from the original.')
        except Exception as exc:
            messagebox.showerror('Cannot open document',str(exc))
        self._refresh_controls()

    def _output_changed(self):
        self.candidate=None;self.result_kind=None
        self.result_view.show_text('Press Improve to build a new candidate.')
        self._refresh_controls()

    def _fill_changes(self):
        self.changelist.delete(0,'end')
        if self.session:
            for c in self.session.changes.values():
                self.changelist.insert('end',('✓' if c.enabled else '–')+'  '+c.field.capitalize()+' — '+c.reason)
        elif self.candidate is not None:
            self.changelist.insert('end','✓  '+self.output.get())

    def _render(self):
        if not self.path:return
        try:
            if self.kind=='PDF':
                i=max(0,min(self.page_index,self.pdf_info.pages-1))
                self.position.set(f'Page {i+1} / {self.pdf_info.pages}')
                im=page_image(self.path,i,scale=self.zoom)
                self.original_view.show_image(im)
                if self.candidate:
                    if self.result_kind=='PDF':
                        self.result_view.show_image(page_image(self.candidate,i,scale=self.zoom))
                    else:
                        self._render_epub_result(i)
                else:
                    self.result_view.show_text('Run Improve to preview changes.')
            else:
                if self.chapter_index<0 and self.has_cover:
                    self.position.set('Cover')
                    self._render_covers()
                    return
                i=max(0,min(self.chapter_index,len(self.source.navnames)-1))
                self.position.set(f'Section {i+1} / {len(self.source.navnames)}')
                self.original_view.show_text(self.source.read_section(i))
                if self.candidate:
                    # The current metadata/cover repair never modifies author
                    # XHTML: compare the same original source-linked passage.
                    self.result_view.show_text(self.source.read_section(i))
                else:self.result_view.show_text('Run Improve to preview changes.')
        except Exception as exc:
            self.status.set(f'Preview failed: {exc}')

    def _render_covers(self):
        def fit(source_bytes, viewer):
            with Image.open(BytesIO(source_bytes)) as im:
                image=im.convert('RGB')
                maxwidth=max(120,viewer.body.winfo_width()-26)
                maxheight=max(240,viewer.body.winfo_height()-25)
                image.thumbnail((maxwidth,maxheight),Image.Resampling.LANCZOS)
                return image
        original=self.source.cover_bytes()
        if original:self.original_view.show_image(fit(original,self.original_view))
        else:self.original_view.show_text('No source cover is identified.')
        if self.candidate is None:
            self.result_view.show_text('Run Improve to preview a new cover.')
            return
        from zipfile import ZipFile
        from lxml import etree
        try:
            with ZipFile(BytesIO(self.candidate)) as z:
                from .core import EPUB_NS,NS
                opf=etree.fromstring(z.read(self.source.opf_path))
                meta=opf.xpath('.//opf:meta[@name="cover"]',namespaces=NS)
                ids=[x.get('content') for x in meta if x.get('content')]
                ids += [x.get('id') for x in opf.xpath('.//opf:manifest/opf:item',namespaces=NS) if 'cover-image' in (x.get('properties') or '').split()]
                ident=next((v for v in ids if v in self.source.paths),None)
                image=z.read(self.source.paths[ident]) if ident in self.source.dimensions else None
            self.result_view.show_image(fit(image,self.result_view)) if image else self.result_view.show_text('No cover.')
        except Exception as exc:self.result_view.show_text('Cover preview failed: '+str(exc))

    def _render_epub_result(self,i):
        if not self.candidate:
            return
        from zipfile import ZipFile
        from io import BytesIO
        try:
            with ZipFile(BytesIO(self.candidate)) as z:
                items=[name for name in z.namelist() if name.endswith('main.xhtml')]
                if not items:raise DocumentError('No readable EPUB content')
                self.result_view.show_text(self._chapter_text(z.read(items[0])))
        except Exception as exc:
            self.result_view.show_text('Result cannot be previewed: '+str(exc))

    @staticmethod
    def _chapter_text(data):
        try:
            root=html.fromstring(data)
            for el in root.xpath('//script|//style|//iframe|//object|//embed'):
                el.drop_tree()
            body=root.xpath('//body')
            node=body[0] if body else root
            lines=[]
            for el in node.iter():
                if el.tag in ('h1','h2','h3','h4','h5','h6','p','li','blockquote','figcaption','td','th'):
                    text=' '.join(' '.join(el.itertext()).split())
                    if text:lines.append(text)
                if el.tag=='img':lines.append('[Image] '+(el.get('alt') or ''))
            if not lines:
                return ' '.join(node.itertext())
            return '\n\n'.join(lines)
        except Exception:
            return '[Unable to parse readable section]'

    def jump(self,event=None):
        if not self.path:return
        selected=self.navigation.curselection()
        if selected:
            if self.kind=='PDF':self.page_index=selected[0]
            else:self.chapter_index=selected[0]-(1 if self.has_cover else 0)
            self._render()

    def shift(self,offset):
        if not self.path:return
        idx=self.page_index if self.kind=='PDF' else self.chapter_index
        count=self.pdf_info.pages if self.kind=='PDF' else len(self.source.navnames)
        low=0 if self.kind=='PDF' or not self.has_cover else -1
        idx=max(low,min(idx+offset,count-1))
        if self.kind=='PDF':self.page_index=idx
        else:self.chapter_index=idx
        nav_idx=idx if self.kind=='PDF' else idx+(1 if self.has_cover else 0)
        self.navigation.selection_clear(0,'end');self.navigation.selection_set(nav_idx)
        self.navigation.see(nav_idx);self._render()

    def resize(self,d):
        self.zoom=max(.5,min(2.0,self.zoom+d));self._render()

    def search(self):
        needle=self.searchtext.get().strip().casefold()
        if not needle or not self.path:return
        if self.kind=='EPUB':
            for i in range(max(0,self.chapter_index),len(self.source.navnames)):
                if needle in self.source.read_section(i).casefold():
                    self.chapter_index=i;self._render();return
        else:
            import pypdfium2 as pdfium
            data=self.candidate if self.candidate is not None and self.result_kind=='PDF' else str(self.path)
            doc=pdfium.PdfDocument(data)
            try:
                for i in range(self.page_index,len(doc)):
                    p=doc[i];t=p.get_textpage();content=t.get_text_range().casefold();t.close();p.close()
                    if needle in content:self.page_index=i;self._render();return
            finally:doc.close()
        self.status.set('Not found in the remaining document sections.')

    def apply_metadata(self):
        if not self.path or self.running:return
        if self.kind=='PDF':
            self.custom_pdf_edits={k:v.get() for k,v in self.meta.items() if v.get().strip()}
            self.status.set('PDF details ready; run Improve to apply.')
            self.candidate=None;self._refresh_controls()
            return
        values={'title':self.meta['title'].get(),'author':self.meta['author'].get(),
                'description':self.description.get('1.0','end-1c'),'cover':self.cover.get()}
        try:
            for k,v in values.items():
                if k=='cover' and not v:continue
                current=self.session.changes.get(k)
                baseline=getattr(self.source.info,'current_cover' if k=='cover' else k,'')
                if v!=baseline and (current is None or current.after!=v):
                    self.session.assign(k,v)
                elif v==baseline and k in self.session.changes:
                    self.session.assign(k,v)
            self.candidate=None;self._fill_changes();self._render();self.status.set('Edit staged. Improve rebuilds the candidate.')
        except DocumentError as exc:messagebox.showerror('Invalid edit',str(exc))
        self._refresh_controls()

    def toggle_change(self):
        if not self.session or self.running:return
        selected=self.changelist.curselection()
        if not selected:return
        field=list(self.session.changes)[selected[0]]
        self.session.toggle(field);self._sync_book_details();self.candidate=None
        self._fill_changes();self._render();self._refresh_controls()

    def _sync_book_details(self):
        if not self.session:return
        current={c.field:c.after for c in self.session.changes.values() if c.enabled}
        self.meta['title'].set(current.get('title',self.source.title))
        self.meta['author'].set(current.get('author',self.source.author))
        self.description.config(state='normal')
        self.description.delete('1.0','end')
        self.description.insert('1.0',current.get('description',self.source.description))
        self.cover.set(current.get('cover',self.source.current_cover or ''))

    def undo(self):
        if self.session:
            self.session.undo();self._sync_book_details()
            self.candidate=None;self._fill_changes();self._render();self._refresh_controls()

    def redo(self):
        if self.session:
            self.session.redo();self._sync_book_details()
            self.candidate=None;self._fill_changes();self._render();self._refresh_controls()

    def _start(self,worker):
        if self.running:return
        self.cancel.clear();self.running=True;self.progress.config(value=0,mode='indeterminate')
        self.progress.start(13);self._refresh_controls()
        def run():
            def progress(done,total,stage):
                self.events.put(('progress',(done,total,stage)))
            try:
                result=worker(progress)
                self.events.put(('done',result))
            except Exception as exc:
                self.events.put(('error',str(exc)))
        threading.Thread(target=run,daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='progress':
                    done,total,label=value
                    self.status.set(label)
                    if total:
                        self.progress.stop();self.progress.configure(mode='determinate',value=100*done/max(1,total))
                    else:
                        self.progress.configure(mode='indeterminate');self.progress.start(13)
                elif kind=='done':
                    self.running=False;self.progress.stop();self.progress.configure(mode='determinate',value=100)
                    if isinstance(value,bytes):
                        self.candidate=value
                        self.status.set('Candidate ready. Review and Save as…')
                        self._fill_changes();self._render()
                    elif isinstance(value,tuple) and value and value[0]=='ai':
                        self.description.config(state='normal')
                        self.description.delete('1.0','end');self.description.insert('1.0',value[1])
                        self.status.set('AI suggestion (not applied). Review and click Apply book details.')
                    else:self.status.set(str(value))
                    self._refresh_controls()
                elif kind=='error':
                    self.running=False;self.progress.stop();self.progress.configure(mode='determinate',value=0)
                    self.status.set('Failed — nothing saved')
                    self._refresh_controls()
                    messagebox.showerror('Processing failed',value)
        except queue.Empty:pass
        self.after(80,self._poll)

    def improve(self):
        if not self.path or self.running:return
        mode=self.output.get()
        if self.kind=='EPUB':
            if not any(c.enabled for c in self.session.changes.values()) and not self.session.extra_css:
                self.status.set('No changes needed. Edit details or cover to propose a repair.')
                return
            self.result_kind='EPUB'
            self._start(lambda p:self.session.build())
        elif mode=='Searchable PDF':
            self.result_kind='PDF'
            self._start(lambda p:searchable_pdf(self.path,progress=p,cancelled=self.cancel.is_set)[0])
        elif mode=='PDF (metadata)':
            self.result_kind='PDF'
            self._start(lambda p:pdf_metadata(self.path,self.custom_pdf_edits))
        elif mode=='EPUB (complex PDF)':
            self.result_kind='EPUB'
            if not has_docling():
                messagebox.showinfo('Engine missing','Advanced PDF processing needs the local Docling engine. No automatic downgrade to text-only conversion.')
                return
            self._start(lambda p:reconstruct_pdf_epub(self.path,progress=p,cancelled=self.cancel.is_set))

    def save(self):
        if self.candidate is None or self.running:return
        suffix='.pdf' if self.result_kind=='PDF' else '.epub'
        suggestion=self.path.with_name(self.path.stem+' - improved'+suffix)
        name=filedialog.asksaveasfilename(initialdir=str(suggestion.parent),initialfile=suggestion.name,
                                          defaultextension=suffix,filetypes=[('PDF','*.pdf')] if suffix=='.pdf' else [('EPUB','*.epub')])
        if not name:return
        if Path(name).resolve()==self.path.resolve():
            messagebox.showerror('Source protected','Choose a new filename. The original cannot be overwritten.')
            return
        try:
            if self.result_kind=='EPUB':
                from zipfile import ZipFile
                with ZipFile(BytesIO(self.candidate)) as z:
                    if z.testzip() is not None:raise DocumentError('Invalid EPUB archive')
                if self.kind=='EPUB':self.source.verify(self.candidate)
            else:
                import pypdfium2 as pdfium
                d=pdfium.PdfDocument(self.candidate)
                try:
                    if len(d)!=self.pdf_info.pages:raise DocumentError('PDF page count mismatch')
                finally:d.close()
            out=atomic_save(name,self.candidate,original=self.path)
            self.status.set(f'Saved and verified: {out.name}')
        except Exception as exc:messagebox.showerror('Export failed',str(exc))

    def setup_engines(self):
        dialog=tk.Toplevel(self);dialog.title('Local engines');dialog.resizable(False,False)
        frame=ttk.Frame(dialog,padding=16);frame.pack(fill='both')
        ttk.Label(frame,text='Optional engines',font=('Segoe UI Semibold',12)).pack(anchor='w',pady=(0,7))
        ttk.Label(frame,text=('The ordinary EPUB/PDF viewer works without AI.\n'
            'OCR needs Tesseract. Advanced layout needs a separate local Docling runtime.\n'
            'Local text AI is downloaded only on request.'),justify='left').pack(anchor='w',pady=(0,9))
        ttk.Label(frame,text='OCR: '+('available' if has_tesseract() else 'not installed in this build')).pack(anchor='w')
        ttk.Label(frame,text='Layout: '+('available' if has_docling() else 'not installed')).pack(anchor='w')
        ttk.Label(frame,text='Text AI: '+('ready' if local_ai.ready() else 'not installed')).pack(anchor='w',pady=(0,10))
        ttk.Button(frame,text='Install advanced PDF/OCR (~12 GB free)',command=lambda:self._start(lambda p:layout_runtime.install(progress=p,cancelled=self.cancel.is_set) and 'PDF layout engine installed')).pack(fill='x',pady=3)
        ttk.Button(frame,text='Install local AI runtime',command=lambda:self._start(lambda p:local_ai.install_engine(progress=p,cancelled=self.cancel.is_set) and 'AI runtime installed')).pack(fill='x',pady=3)
        ttk.Button(frame,text='Download language model (~1.12 GB)',command=lambda:self._start(lambda p:local_ai.install_model(progress=p,cancelled=self.cancel.is_set) and 'Model ready')).pack(fill='x',pady=3)
        ttk.Button(frame,text='Close',command=dialog.destroy).pack(anchor='e',pady=(12,0))

    def suggest_description(self):
        if not self.session or self.running:
            messagebox.showinfo('Unavailable','Open an EPUB first. AI never edits the original book.')
            return
        if not local_ai.ready():
            messagebox.showinfo('Local AI not ready','Install the runtime and model from Extra → Local OCR / AI setup.')
            return
        context=self.source.title+' by '+self.source.author+'\n'+ '\n'.join(self._chapter_text(self.source.chapter_html(i))[:1500] for i in range(min(3,len(self.source.spine))))
        self._start(lambda p:('ai',local_ai.suggest_description(context,cancelled=self.cancel.is_set)))


def main():
    app=App();app.mainloop()


if __name__=='__main__':main()
