"""Compare visible inventory content without treating its position as identity."""
from vision import cv2,np


def snapshot(detector,frame,inventory):
    cells=[]
    for row in range(6):
        line=[]
        for col in range(8):
            x,y=39+col*44.6,63+row*45.5
            patch=detector.region(frame,inventory,(x+2,y+2,x+42,y+43))
            r,g,b=cv2.resize(patch,(40,40),interpolation=cv2.INTER_AREA).astype(np.float32).transpose(2,0,1)
            # Opaque labels/item colors supply evidence; green translucent
            # panel/scene pixels must not identify a row on their own.
            neutral=np.maximum(0,np.minimum(np.minimum(r,g),b)-95)*((np.maximum(np.maximum(r,g),b)-np.minimum(np.minimum(r,g),b))<75)
            red=np.maximum(0,r-np.maximum(g,b)*1.35-15)
            green=np.maximum(0,g-np.maximum(r*1.8,b*2.8)-15)
            blue=np.maximum(0,b-np.maximum(r,g)*1.35-15)
            features=np.stack((neutral,red,green,blue),axis=-1)/160
            line.append(cv2.resize(cv2.GaussianBlur(features,(7,7),2),(16,16),interpolation=cv2.INTER_AREA))
        cells.append(line)
    return np.asarray(cells)


def similarity(a,b):
    a=a.ravel();b=b.ravel()
    energy_a=float(np.dot(a,a));energy_b=float(np.dot(b,b))
    if min(energy_a,energy_b)<.5:return None
    return float(np.dot(a,b)/(energy_a*energy_b)**.5)


def overlap(previous,current):
    """Return a proven 0..5-row downward shift, otherwise no deduplication."""
    scores=[]
    for shift in range(6):
        score=similarity(previous[shift:],current[:6-shift])
        if score is not None:scores.append((score,shift))
    scores.sort(reverse=True)
    if not scores or scores[0][0]<.94:return None
    if len(scores)>1 and scores[0][0]-scores[1][0]<.12:return None
    return scores[0][1]


def checked_overlap(previous,current,checked):
    shift=overlap(previous,current)
    reused=set()
    if shift is not None:
        for row in range(6-shift):
            for col in range(8):
                if (row+shift,col) not in checked:continue
                score=similarity(previous[row+shift,col],current[row,col])
                # Empty cells may be reused only after other, distinctive
                # content proves the scroll displacement, and both are empty.
                empty=float(np.square(previous[row+shift,col]).sum())<.5 and float(np.square(current[row,col]).sum())<.5
                if empty or (score is not None and score>=.96):reused.add((row,col))
    return shift,reused
